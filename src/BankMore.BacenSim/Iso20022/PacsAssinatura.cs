using System.Security.Cryptography.X509Certificates;
using System.Security.Cryptography.Xml;
using System.Xml;

namespace BankMore.BacenSim.Iso20022;

/// <summary>
/// Assinatura e verificação XMLDSig das mensagens ISO 20022 (lado regulador/SPI).
///
/// Manual de Segurança do Pix v6.0, §5.1 — separação de certificados por finalidade.
/// O bacen-sim verifica a assinatura da pacs.008/pacs.004 recebidas do PSP (com o
/// CERTPIA do PSP) e assina a pacs.002 de resposta com o seu próprio CERTPIA
/// (sign-bacen-sim.pfx), distinto do cert de canal mTLS (server.pfx/CERTPIC).
///
/// Espelha (intencionalmente, sem projeto Shared — cada organização implementa a sua
/// mensageria ISO 20022) o PacsAssinatura do PSP. Regra de não-cruzamento: cert de
/// canal (EKU serverAuth/clientAuth) é rejeitado como assinante.
/// </summary>
public sealed class PacsAssinatura
{
    private const string OidServerAuth = "1.3.6.1.5.5.7.3.1";
    private const string OidClientAuth = "1.3.6.1.5.5.7.3.2";

    private readonly X509Certificate2? _certPia;
    private readonly X509Certificate2? _ca;

    public PacsAssinatura(X509Certificate2? certPia, X509Certificate2? ca)
    {
        _certPia = certPia;
        _ca = ca;
    }

    public string Assinar(string xml)
    {
        if (_certPia is null)
            throw new InvalidOperationException("CERTPIA não configurado (assinatura desabilitada)");

        var doc = new XmlDocument { PreserveWhitespace = true };
        doc.LoadXml(xml);

        using var rsa = _certPia.GetRSAPrivateKey()
            ?? throw new InvalidOperationException("CERTPIA sem chave privada utilizável");

        var signedXml = new SignedXml(doc) { SigningKey = rsa };
        signedXml.SignedInfo!.CanonicalizationMethod = SignedXml.XmlDsigExcC14NTransformUrl;

        var reference = new Reference { Uri = "" };
        reference.AddTransform(new XmlDsigEnvelopedSignatureTransform());
        reference.AddTransform(new XmlDsigExcC14NTransform());
        reference.DigestMethod = SignedXml.XmlDsigSHA256Url;
        signedXml.AddReference(reference);
        signedXml.SignedInfo.SignatureMethod = SignedXml.XmlDsigRSASHA256Url;

        var keyInfo = new KeyInfo();
        keyInfo.AddClause(new KeyInfoX509Data(_certPia));
        signedXml.KeyInfo = keyInfo;

        signedXml.ComputeSignature();
        doc.DocumentElement!.AppendChild(doc.ImportNode(signedXml.GetXml(), true));
        return doc.OuterXml;
    }

    public bool Verificar(string xml)
    {
        XmlDocument doc;
        try
        {
            doc = new XmlDocument { PreserveWhitespace = true };
            doc.LoadXml(xml);
        }
        catch { return false; }

        var sigNodes = doc.GetElementsByTagName("Signature", SignedXml.XmlDsigNamespaceUrl);
        if (sigNodes.Count == 0 || sigNodes[0] is not XmlElement sigEl) return false;

        var signedXml = new SignedXml(doc);
        signedXml.LoadXml(sigEl);

        var cert = ObterCertificado(signedXml);
        if (cert is null) return false;

        using var rsaPub = cert.GetRSAPublicKey();
        if (rsaPub is null) return false;

        if (!signedXml.CheckSignature(rsaPub)) return false;
        if (!DerivaDaCa(cert)) return false;
        return EhCertificadoDeAssinatura(cert);
    }

    private static X509Certificate2? ObterCertificado(SignedXml signedXml)
    {
        var keyInfo = signedXml.KeyInfo;
        if (keyInfo is null) return null;
        foreach (var clause in keyInfo)
        {
            if (clause is not KeyInfoX509Data x509 || x509.Certificates is null) continue;
            foreach (var c in x509.Certificates)
                if (c is X509Certificate2 cert) return cert;
        }
        return null;
    }

    private bool DerivaDaCa(X509Certificate2 cert)
    {
        if (_ca is null) return false;
        using var chain = new X509Chain();
        chain.ChainPolicy.TrustMode = X509ChainTrustMode.CustomRootTrust;
        chain.ChainPolicy.CustomTrustStore.Add(_ca);
        chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck;
        return chain.Build(cert);
    }

    private static bool EhCertificadoDeAssinatura(X509Certificate2 cert)
    {
        var temNonRepudiation = false;
        foreach (var ext in cert.Extensions)
        {
            if (ext is X509KeyUsageExtension ku)
                temNonRepudiation = ku.KeyUsages.HasFlag(X509KeyUsageFlags.NonRepudiation)
                                 || ku.KeyUsages.HasFlag(X509KeyUsageFlags.DigitalSignature);

            if (ext is X509EnhancedKeyUsageExtension eku)
            {
                foreach (var oid in eku.EnhancedKeyUsages)
                    if (oid.Value is OidServerAuth or OidClientAuth)
                        return false;
            }
        }
        return temNonRepudiation;
    }
}
