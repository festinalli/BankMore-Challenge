using System.Xml.Linq;

namespace BankMore.BacenSim.Iso20022;

/// <summary>
/// Builders/parsers das mensagens ISO 20022 usadas no SPI brasileiro.
///
/// O SPI (Sistema de Pagamentos Instantâneos) usa um subset do ISO 20022:
///   - pacs.008.001.08  FIToFICstmrCdtTrf   → ordem de pagamento (PSP origem → SPI)
///   - pacs.002.001.10  FIToFIPmtStsRpt     → status report (SPI → PSP)
///   - pacs.004.001.09  PmtRtr              → devolução (MED)
///
/// Aqui geramos XML fiel à estrutura real (namespaces, hierarquia de elementos),
/// sem fazer validação XSD completa (seria overkill pra simulação). O objetivo é
/// demonstrar que o engenheiro entende a mensageria interbancária de verdade —
/// não é um "POST /transfer" REST disfarçado.
/// </summary>
public static class Iso20022Messages
{
    public static readonly XNamespace NsPacs008 = "urn:iso:std:iso:20022:tech:xsd:pacs.008.001.08";
    public static readonly XNamespace NsPacs002 = "urn:iso:std:iso:20022:tech:xsd:pacs.002.001.10";
    public static readonly XNamespace NsPacs004 = "urn:iso:std:iso:20022:tech:xsd:pacs.004.001.09";

    // ---------------------------------------------------------------------
    // pacs.008 — ordem de pagamento (gerada pelo PSP, parseada aqui)
    // ---------------------------------------------------------------------
    public static string BuildPacs008(
        string msgId, string e2eId, string ispbOrigem, string ispbDestino,
        string cpfOrigem, string cpfDestino, decimal valor, DateTimeOffset agora)
    {
        XNamespace ns = NsPacs008;
        var doc = new XElement(ns + "Document",
            new XElement(ns + "FIToFICstmrCdtTrf",
                new XElement(ns + "GrpHdr",
                    new XElement(ns + "MsgId", msgId),
                    new XElement(ns + "CreDtTm", agora.ToString("yyyy-MM-ddTHH:mm:ss.fffzzz")),
                    new XElement(ns + "NbOfTxs", "1"),
                    new XElement(ns + "SttlmInf",
                        new XElement(ns + "SttlmMtd", "CLRG"))),  // clearing
                new XElement(ns + "CdtTrfTxInf",
                    new XElement(ns + "PmtId",
                        new XElement(ns + "EndToEndId", e2eId),
                        new XElement(ns + "TxId", e2eId)),
                    new XElement(ns + "IntrBkSttlmAmt",
                        new XAttribute("Ccy", "BRL"), valor.ToString("F2", System.Globalization.CultureInfo.InvariantCulture)),
                    new XElement(ns + "ChrgBr", "SLEV"),
                    new XElement(ns + "Dbtr",
                        new XElement(ns + "Id",
                            new XElement(ns + "PrvtId",
                                new XElement(ns + "Othr",
                                    new XElement(ns + "Id", cpfOrigem),
                                    new XElement(ns + "SchmeNm",
                                        new XElement(ns + "Prtry", "CPF")))))),
                    new XElement(ns + "DbtrAgt",
                        new XElement(ns + "FinInstnId",
                            new XElement(ns + "ClrSysMmbId",
                                new XElement(ns + "MmbId", ispbOrigem)))),
                    new XElement(ns + "CdtrAgt",
                        new XElement(ns + "FinInstnId",
                            new XElement(ns + "ClrSysMmbId",
                                new XElement(ns + "MmbId", ispbDestino)))),
                    new XElement(ns + "Cdtr",
                        new XElement(ns + "Id",
                            new XElement(ns + "PrvtId",
                                new XElement(ns + "Othr",
                                    new XElement(ns + "Id", cpfDestino),
                                    new XElement(ns + "SchmeNm",
                                        new XElement(ns + "Prtry", "CPF")))))))));
        return new XDocument(new XDeclaration("1.0", "UTF-8", "yes"), doc).ToString();
    }

    public static Pacs008Parsed ParsePacs008(string xml)
    {
        XNamespace ns = NsPacs008;
        var doc = XDocument.Parse(xml);
        var tx = doc.Descendants(ns + "CdtTrfTxInf").First();
        var grpHdr = doc.Descendants(ns + "GrpHdr").First();

        // Extrai o <Othr><Id> (CPF) de dentro de Dbtr (pagador) ou Cdtr (recebedor)
        string ExtractCpf(string parent) =>
            tx.Element(ns + parent)?.Descendants(ns + "Othr").FirstOrDefault()
                ?.Element(ns + "Id")?.Value ?? "";

        return new Pacs008Parsed(
            MsgId: grpHdr.Element(ns + "MsgId")?.Value ?? "",
            E2eId: tx.Descendants(ns + "EndToEndId").FirstOrDefault()?.Value ?? "",
            IspbOrigem: tx.Element(ns + "DbtrAgt")?.Descendants(ns + "MmbId").FirstOrDefault()?.Value ?? "",
            IspbDestino: tx.Element(ns + "CdtrAgt")?.Descendants(ns + "MmbId").FirstOrDefault()?.Value ?? "",
            CpfOrigem: ExtractCpf("Dbtr"),
            CpfDestino: ExtractCpf("Cdtr"),
            Valor: decimal.Parse(tx.Element(ns + "IntrBkSttlmAmt")?.Value ?? "0",
                System.Globalization.CultureInfo.InvariantCulture));
    }

    // ---------------------------------------------------------------------
    // pacs.002 — status report (resposta do SPI)
    // GrpSts: ACSC = AcceptedSettlementCompleted | RJCT = Rejected
    // ---------------------------------------------------------------------
    public static string BuildPacs002(
        string msgId, string origMsgId, string e2eId, string status,
        string? reasonCode, DateTimeOffset agora)
    {
        XNamespace ns = NsPacs002;
        var txSts = new XElement(ns + "TxInfAndSts",
            new XElement(ns + "OrgnlEndToEndId", e2eId),
            new XElement(ns + "TxSts", status));
        if (status == "RJCT" && reasonCode is not null)
        {
            txSts.Add(new XElement(ns + "StsRsnInf",
                new XElement(ns + "Rsn",
                    new XElement(ns + "Cd", reasonCode))));
        }

        var doc = new XElement(ns + "Document",
            new XElement(ns + "FIToFIPmtStsRpt",
                new XElement(ns + "GrpHdr",
                    new XElement(ns + "MsgId", msgId),
                    new XElement(ns + "CreDtTm", agora.ToString("yyyy-MM-ddTHH:mm:ss.fffzzz"))),
                new XElement(ns + "OrgnlGrpInfAndSts",
                    new XElement(ns + "OrgnlMsgId", origMsgId),
                    new XElement(ns + "OrgnlMsgNmId", "pacs.008.001.08")),
                txSts));
        return new XDocument(new XDeclaration("1.0", "UTF-8", "yes"), doc).ToString();
    }

    public static (string Status, string? ReasonCode) ParsePacs002(string xml)
    {
        XNamespace ns = NsPacs002;
        var doc = XDocument.Parse(xml);
        var status = doc.Descendants(ns + "TxSts").FirstOrDefault()?.Value ?? "RJCT";
        var reason = doc.Descendants(ns + "Cd").FirstOrDefault()?.Value;
        return (status, reason);
    }

    // ---------------------------------------------------------------------
    // pacs.004 — devolução (MED / PmtRtr)
    // ---------------------------------------------------------------------
    public static string BuildPacs004(
        string msgId, string rtrId, string origE2eId, decimal valor,
        string reasonCode, string ispbOrigem, string ispbDestino, DateTimeOffset agora)
    {
        XNamespace ns = NsPacs004;
        var doc = new XElement(ns + "Document",
            new XElement(ns + "PmtRtr",
                new XElement(ns + "GrpHdr",
                    new XElement(ns + "MsgId", msgId),
                    new XElement(ns + "CreDtTm", agora.ToString("yyyy-MM-ddTHH:mm:ss.fffzzz")),
                    new XElement(ns + "NbOfTxs", "1")),
                new XElement(ns + "TxInf",
                    new XElement(ns + "RtrId", rtrId),
                    new XElement(ns + "OrgnlEndToEndId", origE2eId),
                    new XElement(ns + "RtrdIntrBkSttlmAmt",
                        new XAttribute("Ccy", "BRL"), valor.ToString("F2", System.Globalization.CultureInfo.InvariantCulture)),
                    new XElement(ns + "RtrRsnInf",
                        new XElement(ns + "Rsn",
                            new XElement(ns + "Cd", reasonCode))))));
        return new XDocument(new XDeclaration("1.0", "UTF-8", "yes"), doc).ToString();
    }
}

public sealed record Pacs008Parsed(
    string MsgId, string E2eId, string IspbOrigem, string IspbDestino,
    string CpfOrigem, string CpfDestino, decimal Valor);
