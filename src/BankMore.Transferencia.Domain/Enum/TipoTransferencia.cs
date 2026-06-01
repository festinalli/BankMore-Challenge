using System.ComponentModel;

namespace BankMore.Transferencia.Domain.Enums
{
    /// <summary>
    /// Representa os tipos de transferência disponíveis no sistema.
    /// Centraliza as regras de negócio de tarifas e descrições.
    /// </summary>
    public enum TipoTransferencia
    {
        [Description("PIX")]
        PIX = 0,

        [Description("TED")]
        TED = 1,

        [Description("TEF")]
        TEF = 2
    }

        public static class TipoTransferenciaExtensions
    {
        /// <summary>
        /// Regra de Negócio: Define o valor da tarifa para cada tipo de operação.
        /// </summary>
        public static decimal ObterValorTarifa(this TipoTransferencia tipo) => tipo switch
        {
            TipoTransferencia.TED => 4.00m,
            TipoTransferencia.TEF => 1.00m,
            TipoTransferencia.PIX => 0.00m,
            _ => 0.00m
        };

        /// <summary>
        /// Retorna a descrição formatada para exibição no extrato do cliente.
        /// </summary>
        public static string ObterDescricaoExtrato(this TipoTransferencia tipo) => tipo switch
        {
            TipoTransferencia.TED => "Taxa de Transferência TED",
            TipoTransferencia.TEF => "Taxa de Transferência TEF",
            TipoTransferencia.PIX => "Taxa de Transferência PIX",
            _ => "Taxa de Transferência"
        };
    }
}
