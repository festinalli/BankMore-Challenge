using System.Security.Cryptography.X509Certificates;
using System.Security.Cryptography.Xml;
using System.Xml;

namespace BankMore.Pix.Infrastructure;

/// <summary>
/// Assinatura e verificação XMLDSig das mensagens ISO 20022 do PIX (lado PSP).
///
/// Manual de Segurança do Pix v6.0, §5.1 — separação de certificados por finalidade:
/// a autenticidade/integridade da MENSAGEM (não-repúdio por mensagem, sobrevive ao
/// trânsito e em repouso) é provida por um certificado de ASSINATURA (CERTPIA),
/// DISTINTO do certificado de autenticação de CANAL (CERTPIC/mTLS). O pix-api assina
/// a pacs.008/pacs.004 com o seu CERTPIA (sign-pix-api.pfx) e verifica a pacs.002
/// assinada pelo regulador.
///
/// Regra de não-cruzamento (verificação): um certificado de canal (com EKU
/// serverAuth/clientAuth) é REJEITADO como assinante — só vale CERTPIA (keyUsage
/// nonRepudiation, sem EKU de TLS). Assim o CERTPIC nunca assina mensagem.
///
/// Em produção o CERTPIA seria A1/A3 da ICP-Brasil, guardado em HSM/token; aqui é
/// emitido pela CA self-signed que faz o papel da AC Raiz.
/// </summary>
public sealed class PacsAssinatura
{
    // OIDs de EKU de TLS — um cert de canal os carrega; um CERTPIA não pode.
    private const string OidServerAuth = "1.3.6.1.5.5.7.3.1";
    private const string OidClientAuth = "1.3.6.1.5.5.7.3.2";

    private readonly X509Certificate2? _certPia; // com chave privada; null se assinatura desabilitada
    private readonly X509Certificate2? _ca;       // null quando assinatura desabilitada

    public PacsAssinatura(X509Certificate2? certPia, X509Certificate2? ca)
    {
        _certPia = certPia;
        _ca = ca;
    }

    /// <summary>Assina o XML (envelope enveloped + Exclusive C14N) com o CERTPIA.</summary>
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

    /// <summary>
    /// Verifica a assinatura: (1) íntegra com a chave do cert embutido no KeyInfo;
    /// (2) o cert deriva da CA confiável; (3) o cert é um CERTPIA (não-cruzamento de
    /// finalidade). Retorna false se faltar assinatura ou qualquer checagem falhar.
    /// </summary>
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

        // (1) assinatura matematicamente válida sob a chave do cert embutido
        if (!signedXml.CheckSignature(rsaPub)) return false;
        // (2) cadeia confiável até a CA
        if (!DerivaDaCa(cert)) return false;
        // (3) não-cruzamento: tem que ser CERTPIA, não um cert de canal
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
        chain.ChainPolicy.RevocationMode = X509RevocationMode.NoCheck; // sim: sem OCSP/CRL (prod exige)
        return chain.Build(cert);
    }

    /// <summary>
    /// CERTPIA = keyUsage com NonRepudiation (ou DigitalSignature) E sem EKU de TLS.
    /// Um cert de canal (serverAuth/clientAuth) é rejeitado → CERTPIC nunca assina.
    /// </summary>
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
                        return false; // é cert de canal — não pode assinar mensagem
            }
        }
        return temNonRepudiation;
    }
}

/// <summary>
/// Flag de assinatura de mensagem (Manual Pix v6.0 §5.1). Quando desabilitada, o
/// fluxo cai para mTLS-só (compat retroativa). Registrada como singleton no Program.cs.
/// </summary>
public sealed record PixSignConfig(bool Habilitado);
