using System.Globalization;
using System.Text;

namespace BankMore.Pix.Domain;

/// <summary>
/// BR Code — o payload do QR Code PIX, baseado no padrão EMVCo MPM
/// (Merchant Presented Mode) com os campos do arranjo PIX (Manual de Padrões
/// para Iniciação do PIX, BACEN).
///
/// Estrutura TLV (Tag-Length-Value): cada campo é "ID(2) + tamanho(2) + valor".
/// O campo 26 (Merchant Account Information) carrega o GUI "br.gov.bcb.pix" + a
/// chave (ou URL do payload dinâmico). O campo 63 é o CRC16-CCITT do payload
/// inteiro (incluindo "6304").
///
/// Estático:  chave + valor opcional, sem txid (usa "***")
/// Dinâmico:  campo 26 carrega a URL do payload (PSP resolve via GET) + txid real
/// </summary>
public static class BrCode
{
    private const string GuiPix = "br.gov.bcb.pix";

    /// <summary>QR estático: paga direto pra uma chave, valor fixo ou aberto.</summary>
    public static string GerarEstatico(string chave, decimal? valor, string nomeRecebedor, string cidade, string? txid = null)
    {
        var mai = Tlv("00", GuiPix) + Tlv("01", chave);

        var sb = new StringBuilder();
        sb.Append(Tlv("00", "01"));                       // Payload Format Indicator
        sb.Append(Tlv("01", "11"));                       // Point of Initiation (11=estático reutilizável)
        sb.Append(Tlv("26", mai));                        // Merchant Account Info (PIX)
        sb.Append(Tlv("52", "0000"));                     // Merchant Category Code
        sb.Append(Tlv("53", "986"));                      // Moeda (986 = BRL)
        if (valor is > 0)
            sb.Append(Tlv("54", valor.Value.ToString("F2", CultureInfo.InvariantCulture)));
        sb.Append(Tlv("58", "BR"));                       // País
        sb.Append(Tlv("59", Truncar(nomeRecebedor, 25))); // Nome recebedor
        sb.Append(Tlv("60", Truncar(cidade, 15)));        // Cidade
        sb.Append(Tlv("62", Tlv("05", txid ?? "***")));   // Additional Data (txid)

        return ComCrc(sb.ToString());
    }

    /// <summary>
    /// QR dinâmico: o campo 26 carrega a URL do payload JWS (location). O PSP do
    /// pagador faz GET nessa URL pra obter valor/vencimento. txid é obrigatório (26 chars).
    /// </summary>
    public static string GerarDinamico(string urlPayload, string nomeRecebedor, string cidade, string txid)
    {
        var mai = Tlv("00", GuiPix) + Tlv("25", urlPayload);  // 25 = URL (dinâmico)

        var sb = new StringBuilder();
        sb.Append(Tlv("00", "01"));
        sb.Append(Tlv("01", "12"));                       // 12 = dinâmico (uso único)
        sb.Append(Tlv("26", mai));
        sb.Append(Tlv("52", "0000"));
        sb.Append(Tlv("53", "986"));
        sb.Append(Tlv("58", "BR"));
        sb.Append(Tlv("59", Truncar(nomeRecebedor, 25)));
        sb.Append(Tlv("60", Truncar(cidade, 15)));
        sb.Append(Tlv("62", Tlv("05", txid)));

        return ComCrc(sb.ToString());
    }

    // --- TLV helpers ---
    private static string Tlv(string id, string value) =>
        $"{id}{value.Length:D2}{value}";

    private static string ComCrc(string payloadSemCrc)
    {
        // "6304" = tag 63, length 04. O CRC é calculado sobre o payload + "6304".
        var comTag = payloadSemCrc + "6304";
        var crc = Crc16Ccitt(comTag);
        return comTag + crc;
    }

    /// <summary>CRC16-CCITT (poly 0x1021, init 0xFFFF) — exigido pelo EMVCo no campo 63.</summary>
    public static string Crc16Ccitt(string data)
    {
        ushort crc = 0xFFFF;
        foreach (var b in Encoding.UTF8.GetBytes(data))
        {
            crc ^= (ushort)(b << 8);
            for (var i = 0; i < 8; i++)
                crc = (crc & 0x8000) != 0 ? (ushort)((crc << 1) ^ 0x1021) : (ushort)(crc << 1);
        }
        return crc.ToString("X4");
    }

    private static string Truncar(string s, int max) =>
        s.Length <= max ? s : s.Substring(0, max);

    /// <summary>txid do PIX dinâmico: 1-25 chars [A-Za-z0-9] (BACEN limita a 25 no QR).</summary>
    public static string GerarTxid()
    {
        const string alfa = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
        Span<char> buf = stackalloc char[25];
        for (var i = 0; i < buf.Length; i++)
            buf[i] = alfa[System.Security.Cryptography.RandomNumberGenerator.GetInt32(alfa.Length)];
        return new string(buf);
    }
}
