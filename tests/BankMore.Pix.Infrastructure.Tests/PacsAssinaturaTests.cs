using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using BankMore.Pix.Infrastructure;
using Xunit;

namespace BankMore.Pix.Infrastructure.Tests;

/// <summary>
/// Testes do PacsAssinatura — núcleo da conformidade §5.1 (Manual de Segurança do
/// Pix v6.0): assinatura XMLDSig das mensagens ISO 20022 com separação de finalidade.
///
/// Os certificados são emitidos em código (CA self-signed + CERTPIA de assinatura +
/// CERTPIC de canal) pra os testes serem auto-contidos e determinísticos — sem
/// depender dos arquivos de infra/certs.
/// </summary>
public class PacsAssinaturaTests
{
    // pacs.008 mínima mas bem-formada (o assinador não valida XSD, só assina o documento).
    private const string Pacs008 =
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>" +
        "<Document xmlns=\"urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08\">" +
        "<FIToFICstmrCdtTrf><GrpHdr><MsgId>M-ABC-123</MsgId><NbOfTxs>1</NbOfTxs></GrpHdr>" +
        "<CdtTrfTxInf><PmtId><EndToEndId>E12345678</EndToEndId></PmtId></CdtTrfTxInf>" +
        "</FIToFICstmrCdtTrf></Document>";

    [Fact]
    public void Assinar_E_Verificar_FazRoundTrip()
    {
        using var ca = TestPki.CriarCa();
        using var certPia = TestPki.CriarCertPia(ca);
        var sut = new PacsAssinatura(certPia, TestPki.SoPublico(ca));

        var assinado = sut.Assinar(Pacs008);

        Assert.Contains("Signature", assinado);      // assinatura embutida
        Assert.True(sut.Verificar(assinado));         // verifica com sucesso
    }

    [Fact]
    public void Verificar_MensagemSemAssinatura_Rejeita()
    {
        using var ca = TestPki.CriarCa();
        var sut = new PacsAssinatura(null, TestPki.SoPublico(ca));

        Assert.False(sut.Verificar(Pacs008));         // sem <Signature> → false
    }

    [Fact]
    public void Verificar_XmlAdulteradoAposAssinar_Rejeita()
    {
        using var ca = TestPki.CriarCa();
        using var certPia = TestPki.CriarCertPia(ca);
        var sut = new PacsAssinatura(certPia, TestPki.SoPublico(ca));

        var assinado = sut.Assinar(Pacs008);
        // adultera o conteúdo (fora do bloco de assinatura) → digest não bate
        var adulterado = assinado.Replace("M-ABC-123", "M-XYZ-999");

        Assert.NotEqual(assinado, adulterado);
        Assert.False(sut.Verificar(adulterado));
    }

    [Fact]
    public void Verificar_AssinadoComCertificadoDeCanal_Rejeita_NaoCruzamento()
    {
        // §5.1 — o cert de CANAL (CERTPIC, EKU clientAuth) NÃO pode assinar mensagem.
        using var ca = TestPki.CriarCa();
        using var certCanal = TestPki.CriarCertCanal(ca);     // clientAuth
        var caPublico = TestPki.SoPublico(ca);

        var assinanteIndevido = new PacsAssinatura(certCanal, caPublico);
        var assinado = assinanteIndevido.Assinar(Pacs008);    // assina com cert de canal

        var verificador = new PacsAssinatura(null, caPublico);
        // assinatura é íntegra e o cert deriva da CA, mas é cert de canal → rejeitado
        Assert.False(verificador.Verificar(assinado));
    }

    [Fact]
    public void Verificar_CertificadoDeOutraCa_Rejeita()
    {
        using var caConfiavel = TestPki.CriarCa("CA Confiavel");
        using var caEstranha = TestPki.CriarCa("CA Estranha");
        using var piaEstranho = TestPki.CriarCertPia(caEstranha);

        var assinante = new PacsAssinatura(piaEstranho, TestPki.SoPublico(caEstranha));
        var assinado = assinante.Assinar(Pacs008);

        var verificador = new PacsAssinatura(null, TestPki.SoPublico(caConfiavel));
        Assert.False(verificador.Verificar(assinado));        // cadeia não chega na CA confiável
    }

    [Fact]
    public void Assinar_SemCertPia_Lanca()
    {
        using var ca = TestPki.CriarCa();
        var sut = new PacsAssinatura(null, TestPki.SoPublico(ca));

        Assert.Throws<InvalidOperationException>(() => sut.Assinar(Pacs008));
    }

    [Fact]
    public void Verificar_LixoNaoXml_RetornaFalseSemLancar()
    {
        using var ca = TestPki.CriarCa();
        var sut = new PacsAssinatura(null, TestPki.SoPublico(ca));

        Assert.False(sut.Verificar("isto não é xml"));
    }
}

/// <summary>Emissor de certificados de teste (CA + CERTPIA + CERTPIC) via APIs do .NET.</summary>
internal static class TestPki
{
    private const string OidClientAuth = "1.3.6.1.5.5.7.3.2";

    public static X509Certificate2 CriarCa(string cn = "Test Root CA")
    {
        using var rsa = RSA.Create(2048);
        var req = new CertificateRequest($"CN={cn}", rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        req.CertificateExtensions.Add(new X509BasicConstraintsExtension(true, false, 0, true));
        req.CertificateExtensions.Add(
            new X509KeyUsageExtension(X509KeyUsageFlags.KeyCertSign | X509KeyUsageFlags.CrlSign, true));
        req.CertificateExtensions.Add(new X509SubjectKeyIdentifierExtension(req.PublicKey, false));
        return req.CreateSelfSigned(DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddYears(5));
    }

    /// <summary>CERTPIA: keyUsage digitalSignature+nonRepudiation, SEM EKU de TLS.</summary>
    public static X509Certificate2 CriarCertPia(X509Certificate2 ca, string cn = "pix-api-sign")
        => EmitirFolha(ca, cn, X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.NonRepudiation, eku: null);

    /// <summary>CERTPIC (canal): keyUsage digitalSignature+keyEncipherment + EKU clientAuth.</summary>
    public static X509Certificate2 CriarCertCanal(X509Certificate2 ca, string cn = "pix-api")
        => EmitirFolha(ca, cn, X509KeyUsageFlags.DigitalSignature | X509KeyUsageFlags.KeyEncipherment,
            eku: new OidCollection { new Oid(OidClientAuth) });

    /// <summary>Cópia só com a parte pública (como o ca.crt montado nos serviços).</summary>
    public static X509Certificate2 SoPublico(X509Certificate2 cert)
        => new(cert.Export(X509ContentType.Cert));

    private static X509Certificate2 EmitirFolha(X509Certificate2 ca, string cn, X509KeyUsageFlags ku, OidCollection? eku)
    {
        var rsa = RSA.Create(2048);
        var req = new CertificateRequest($"CN={cn}", rsa, HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
        req.CertificateExtensions.Add(new X509BasicConstraintsExtension(false, false, 0, false));
        req.CertificateExtensions.Add(new X509KeyUsageExtension(ku, true));
        if (eku is not null)
            req.CertificateExtensions.Add(new X509EnhancedKeyUsageExtension(eku, false));
        req.CertificateExtensions.Add(new X509SubjectKeyIdentifierExtension(req.PublicKey, false));

        var serial = new byte[8];
        RandomNumberGenerator.Fill(serial);
        using var emitido = req.Create(ca, DateTimeOffset.UtcNow.AddDays(-1), DateTimeOffset.UtcNow.AddYears(2), serial);
        return emitido.CopyWithPrivateKey(rsa); // cert COM chave privada (pra assinar)
    }
}
