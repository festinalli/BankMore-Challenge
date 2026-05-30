namespace BankMore.Pix.Domain;

/// <summary>Chave PIX registrada no DICT, vinculada a uma conta local.</summary>
public sealed class PixChave
{
    public Guid Id { get; init; } = Guid.NewGuid();
    public TipoChave Tipo { get; init; }
    public string ValorChave { get; init; } = "";
    public string IdContaCorrente { get; init; } = "";
    public string Ispb { get; init; } = "12345678";
    public string Status { get; set; } = "ATIVA";
    public DateTimeOffset CriadoEm { get; init; } = DateTimeOffset.UtcNow;
}

/// <summary>Pagamento PIX — agrega a state machine de liquidação.</summary>
public sealed class PixPagamento
{
    public Guid Id { get; init; } = Guid.NewGuid();
    public string E2eId { get; init; } = "";
    public string CpfOrigem { get; init; } = "";
    public string? ChaveDestino { get; set; }
    public string? CpfDestino { get; set; }
    public string? IspbDestino { get; set; }
    public decimal Valor { get; init; }
    public TipoIniciacao TipoIniciacao { get; init; } = TipoIniciacao.MANUAL;
    public string? Txid { get; set; }
    public StatusPagamento Status { get; set; } = StatusPagamento.INICIADO;
    public string? MotivoRejeicao { get; set; }
    public decimal? ScoreFraude { get; set; }
    public string? ModeloVersao { get; set; }
    public string? Pacs008Xml { get; set; }
    public string? Pacs002Xml { get; set; }
    public string CorrelationId { get; init; } = "";
    public DateTimeOffset IniciadoEm { get; init; } = DateTimeOffset.UtcNow;
    public DateTimeOffset? LiquidadoEm { get; set; }
}

/// <summary>Devolução MED.</summary>
public sealed class PixDevolucao
{
    public Guid Id { get; init; } = Guid.NewGuid();
    public string DevolutionId { get; init; } = "";
    public Guid PagamentoId { get; init; }
    public decimal Valor { get; init; }
    public MotivoDevolucao Motivo { get; init; }
    public StatusDevolucao Status { get; set; } = StatusDevolucao.SOLICITADA;
    public string? Pacs004Xml { get; set; }
    public DateTimeOffset SolicitadoEm { get; init; } = DateTimeOffset.UtcNow;
    public DateTimeOffset PrazoLimite { get; init; }
    public DateTimeOffset? ResolvidoEm { get; set; }
}

/// <summary>Consentimento — PIX Automático ou Open Finance.</summary>
public sealed class PixConsentimento
{
    public Guid Id { get; init; } = Guid.NewGuid();
    public TipoConsentimento Tipo { get; init; }
    public string CpfPagador { get; init; } = "";
    public string ChaveRecebedor { get; init; } = "";
    public decimal? ValorFixo { get; init; }
    public decimal? ValorMaximo { get; init; }
    public string? Periodicidade { get; init; }
    public DateOnly? DataInicio { get; init; }
    public DateOnly? DataFim { get; init; }
    public StatusConsentimento Status { get; set; } = StatusConsentimento.CRIADO;
    public DateTimeOffset? ProximaCobranca { get; set; }
    public string? IdTerceiro { get; init; }
    public DateTimeOffset CriadoEm { get; init; } = DateTimeOffset.UtcNow;
    public DateTimeOffset? AutorizadoEm { get; set; }
}

/// <summary>QR Code BR Code gerado.</summary>
public sealed class PixQrCode
{
    public Guid Id { get; init; } = Guid.NewGuid();
    public string Txid { get; init; } = "";
    public TipoQrCode Tipo { get; init; }
    public string Chave { get; init; } = "";
    public decimal? Valor { get; init; }
    public string PayloadEmv { get; init; } = "";
    public string? Descricao { get; init; }
    public string Status { get; set; } = "ATIVO";
    public DateTimeOffset? Vencimento { get; init; }
    public DateTimeOffset CriadoEm { get; init; } = DateTimeOffset.UtcNow;
}

/// <summary>Token efêmero do PIX por Aproximação (NFC).</summary>
public sealed class PixNfcToken
{
    public Guid Id { get; init; } = Guid.NewGuid();
    public string Token { get; init; } = "";
    public string IdContaCorrente { get; init; } = "";
    public decimal ValorMaximo { get; init; }
    public string Status { get; set; } = "ATIVO";
    public DateTimeOffset ExpiraEm { get; init; }
    public DateTimeOffset? UsadoEm { get; set; }
    public DateTimeOffset CriadoEm { get; init; } = DateTimeOffset.UtcNow;
}
