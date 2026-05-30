namespace BankMore.Pix.Domain;

public enum TipoChave { CPF, CNPJ, EMAIL, TELEFONE, EVP }

public enum TipoIniciacao { MANUAL, QRCODE_ESTATICO, QRCODE_DINAMICO, NFC, AUTOMATICO, OPEN_FINANCE }

public enum StatusPagamento { INICIADO, RESOLVENDO_CHAVE, LIQUIDANDO, LIQUIDADO, REJEITADO, DEVOLVIDO }

public enum TipoQrCode { ESTATICO, DINAMICO, COBV }

public enum MotivoDevolucao { FRAUDE, ERRO_OPERACIONAL, SOLICITACAO_CLIENTE }

public enum StatusDevolucao { SOLICITADA, BLOQUEADO, DEVOLVIDO, LIBERADO, NEGADO }

public enum TipoConsentimento { AUTOMATICO, OPEN_FINANCE }

public enum StatusConsentimento { CRIADO, AUTORIZADO, CONSUMIDO, CANCELADO, EXPIRADO, REJEITADO }
