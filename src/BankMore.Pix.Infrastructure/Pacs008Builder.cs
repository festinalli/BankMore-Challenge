using System.Globalization;
using System.Xml.Linq;

namespace BankMore.Pix.Infrastructure;

/// <summary>
/// Builder do pacs.008 do lado do PSP pagador (BankMore).
///
/// NOTA arquitetural: o bacen-sim tem seu próprio parser/builder ISO 20022. Aqui o
/// PSP tem o SEU builder — não é duplicação acidental, é a realidade do PIX: cada
/// instituição implementa independentemente a serialização do mesmo schema XSD. Um
/// projeto BankMore.Shared.Iso20022 seria possível, mas acoplaria PSP e simulador
/// do regulador, o que não reflete a topologia real (são organizações distintas).
/// </summary>
public static class Pacs008Builder
{
    private static readonly XNamespace Ns = "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08";

    public static string Build(
        string msgId, string e2eId, string ispbOrigem, string ispbDestino,
        string cpfOrigem, string cpfDestino, decimal valor, DateTimeOffset agora)
    {
        var doc = new XElement(Ns + "Document",
            new XElement(Ns + "FIToFICstmrCdtTrf",
                new XElement(Ns + "GrpHdr",
                    new XElement(Ns + "MsgId", msgId),
                    new XElement(Ns + "CreDtTm", agora.ToString("yyyy-MM-ddTHH:mm:ss.fffzzz")),
                    new XElement(Ns + "NbOfTxs", "1"),
                    new XElement(Ns + "SttlmInf", new XElement(Ns + "SttlmMtd", "CLRG"))),
                new XElement(Ns + "CdtTrfTxInf",
                    new XElement(Ns + "PmtId",
                        new XElement(Ns + "EndToEndId", e2eId),
                        new XElement(Ns + "TxId", e2eId)),
                    new XElement(Ns + "IntrBkSttlmAmt",
                        new XAttribute("Ccy", "BRL"), valor.ToString("F2", CultureInfo.InvariantCulture)),
                    new XElement(Ns + "ChrgBr", "SLEV"),
                    new XElement(Ns + "Dbtr",
                        new XElement(Ns + "Id", new XElement(Ns + "PrvtId", new XElement(Ns + "Othr",
                            new XElement(Ns + "Id", cpfOrigem),
                            new XElement(Ns + "SchmeNm", new XElement(Ns + "Prtry", "CPF")))))),
                    new XElement(Ns + "DbtrAgt", new XElement(Ns + "FinInstnId",
                        new XElement(Ns + "ClrSysMmbId", new XElement(Ns + "MmbId", ispbOrigem)))),
                    new XElement(Ns + "CdtrAgt", new XElement(Ns + "FinInstnId",
                        new XElement(Ns + "ClrSysMmbId", new XElement(Ns + "MmbId", ispbDestino)))),
                    new XElement(Ns + "Cdtr",
                        new XElement(Ns + "Id", new XElement(Ns + "PrvtId", new XElement(Ns + "Othr",
                            new XElement(Ns + "Id", cpfDestino),
                            new XElement(Ns + "SchmeNm", new XElement(Ns + "Prtry", "CPF")))))))));
        return new XDocument(new XDeclaration("1.0", "UTF-8", "yes"), doc).ToString();
    }

    private static readonly XNamespace NsPacs004 = "urn:iso:std:iso:20022:tech:xsd:pacs.004.001.09";

    public static string BuildPacs004(
        string msgId, string rtrId, string origE2eId, decimal valor,
        string reasonCode, string ispbOrigem, string ispbDestino, DateTimeOffset agora)
    {
        var doc = new XElement(NsPacs004 + "Document",
            new XElement(NsPacs004 + "PmtRtr",
                new XElement(NsPacs004 + "GrpHdr",
                    new XElement(NsPacs004 + "MsgId", msgId),
                    new XElement(NsPacs004 + "CreDtTm", agora.ToString("yyyy-MM-ddTHH:mm:ss.fffzzz")),
                    new XElement(NsPacs004 + "NbOfTxs", "1")),
                new XElement(NsPacs004 + "TxInf",
                    new XElement(NsPacs004 + "RtrId", rtrId),
                    new XElement(NsPacs004 + "OrgnlEndToEndId", origE2eId),
                    new XElement(NsPacs004 + "RtrdIntrBkSttlmAmt",
                        new XAttribute("Ccy", "BRL"), valor.ToString("F2", CultureInfo.InvariantCulture)),
                    new XElement(NsPacs004 + "RtrRsnInf",
                        new XElement(NsPacs004 + "Rsn", new XElement(NsPacs004 + "Cd", reasonCode))))));
        return new XDocument(new XDeclaration("1.0", "UTF-8", "yes"), doc).ToString();
    }
}
