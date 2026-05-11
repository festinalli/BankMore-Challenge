using MediatR;
using KafkaFlow;
using KafkaFlow.Producers;
using BankMore.Transferencia.Domain.Enums;

namespace BankMore.Transferencia.Application.Handlers
{
    public record EfetuarTransferenciaCommand(
        string CpfOrigem,
        string CpfDestino,
        decimal Valor,
        TipoTransferencia Tipo,
        string CorrelationId
    ) : IRequest<EfetuarTransferenciaResult>;

    public record EfetuarTransferenciaResult(string Id, string CorrelationId, string Status);

    /// <summary>
    /// Evento publicado em <c>transferencia.solicitada</c>.
    /// Contrato canônico — alinhado com <c>contracts/avro/transferencia-solicitada.avsc</c>.
    /// Sprint 1: JSON. Sprint 2: migra para Avro + Schema Registry.
    /// </summary>
    public class TransferenciaSolicitadaMessage
    {
        public string Id { get; set; } = string.Empty;
        public string CorrelationId { get; set; } = string.Empty;
        public string CpfOrigem { get; set; } = string.Empty;
        public string CpfDestino { get; set; } = string.Empty;
        public decimal Valor { get; set; }
        public string Tipo { get; set; } = string.Empty;
        public decimal Taxa { get; set; }
        public long Timestamp { get; set; }
        public string Canal { get; set; } = "WEB";
    }

    public class EfetuarTransferenciaHandler(IProducerAccessor producers) : IRequestHandler<EfetuarTransferenciaCommand, EfetuarTransferenciaResult>
    {
        private const string ProducerName = "transferencia-producer";

        public async Task<EfetuarTransferenciaResult> Handle(EfetuarTransferenciaCommand request, CancellationToken cancellationToken)
        {
            var producer = producers.GetProducer(ProducerName);
            var id = Guid.NewGuid().ToString();

            var message = new TransferenciaSolicitadaMessage
            {
                Id = id,
                CorrelationId = request.CorrelationId,
                CpfOrigem = request.CpfOrigem,
                CpfDestino = request.CpfDestino,
                Valor = request.Valor,
                Tipo = request.Tipo.ToString(),
                Taxa = request.Tipo.ObterValorTarifa(),
                Timestamp = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(),
                Canal = "WEB"
            };

            await producer.ProduceAsync(request.CpfOrigem, message);

            return new EfetuarTransferenciaResult(id, request.CorrelationId, "SOLICITADA");
        }
    }
}
