using System.Security.Cryptography;

namespace BankMore.Pix.Domain;

/// <summary>
/// EndToEndId — identificador único de ponta-a-ponta de cada PIX, definido pelo BACEN.
///
/// Formato (32 chars): E + ISPB(8) + AAAAMMDDHHMM(12) + sufixo aleatório(11)
///   E         literal
///   ISPB      ISPB do PSP do pagador (8 dígitos)
///   timestamp ano-mês-dia-hora-minuto da criação
///   sufixo    11 chars [A-Za-z0-9] gerados pelo PSP, únicos no minuto
///
/// É o mesmo id usado no campo EndToEndId do pacs.008 e ecoado no pacs.002.
/// Devoluções (pacs.004) usam o RtrId, com prefixo 'D'.
/// </summary>
public static class EndToEndId
{
    private const string Alfabeto = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";

    public static string Gerar(string ispb, DateTimeOffset? agora = null)
    {
        var ts = (agora ?? DateTimeOffset.UtcNow).ToString("yyyyMMddHHmm");
        return $"E{ispb}{ts}{SufixoAleatorio(11)}";
    }

    /// <summary>RtrId da devolução MED (mesmo formato, prefixo D).</summary>
    public static string GerarDevolucao(string ispb, DateTimeOffset? agora = null)
    {
        var ts = (agora ?? DateTimeOffset.UtcNow).ToString("yyyyMMddHHmm");
        return $"D{ispb}{ts}{SufixoAleatorio(11)}";
    }

    private static string SufixoAleatorio(int n)
    {
        Span<char> buf = stackalloc char[n];
        for (var i = 0; i < n; i++)
            buf[i] = Alfabeto[RandomNumberGenerator.GetInt32(Alfabeto.Length)];
        return new string(buf);
    }
}
