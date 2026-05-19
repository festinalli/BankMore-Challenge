using MediatR;
using BankMore.Transferencia.Domain;
using BankMore.Transferencia.Domain.Enums;
using TransferenciaEntity = BankMore.Transferencia.Domain.Transferencia;

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

    public class EfetuarTransferenciaHandler(
        ITransferenciaRepository repository
    ) : IRequestHandler<EfetuarTransferenciaCommand, EfetuarTransferenciaResult>
    {
        // Sprint 5.B — Outbox pattern: NÃO publica no Kafka direto.
        // Handler grava transferencia + outbox row na MESMA TX.
        // OutboxRelayHostedService publica do outbox de forma assíncrona com retries.
        public const string TopicSolicitada = "transferencia.solicitada";

        public async Task<EfetuarTransferenciaResult> Handle(
            EfetuarTransferenciaCommand request, CancellationToken cancellationToken)
        {
            var id = Guid.NewGuid().ToString();
            var now = DateTime.UtcNow;

            var transferencia = new TransferenciaEntity
            {
                Id = id,
                CorrelationId = request.CorrelationId,
                CpfOrigem = request.CpfOrigem,
                CpfDestino = request.CpfDestino,
                Valor = request.Valor,
                Tipo = request.Tipo.ToString(),
                Status = "SOLICITADA",
                SolicitadaEm = now
            };

            var message = new TransferenciaSolicitadaMessage
            {
                Id = id,
                CorrelationId = request.CorrelationId,
                CpfOrigem = request.CpfOrigem,
                CpfDestino = request.CpfDestino,
                Valor = request.Valor,
                Tipo = request.Tipo.ToString(),
                Taxa = request.Tipo.ObterValorTarifa(),
                Timestamp = new DateTimeOffset(now).ToUnixTimeMilliseconds(),
                Canal = "WEB"
            };

            // Serializa pra JSON canônico (camelCase pra ficar consistente com o detector).
            var payloadJson = Newtonsoft.Json.JsonConvert.SerializeObject(
                message,
                new Newtonsoft.Json.JsonSerializerSettings
                {
                    ContractResolver = new Newtonsoft.Json.Serialization.CamelCasePropertyNamesContractResolver()
                });

            // Uma transação: transferencia + outbox row. Se algo falha, ROLLBACK total.
            await repository.PersistirSolicitadaComOutbox(
                transferencia, TopicSolicitada, payloadJson, cancellationToken);

            return new EfetuarTransferenciaResult(id, request.CorrelationId, "SOLICITADA");
        }
    }
}
