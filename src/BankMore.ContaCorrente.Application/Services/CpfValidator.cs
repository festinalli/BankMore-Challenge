namespace BankMore.ContaCorrente.Application.Services
{
    /// <summary>
    /// Validador de CPF com os 2 dígitos verificadores (algoritmo Receita Federal).
    /// Aceita CPF com ou sem máscara — normaliza removendo não-dígitos.
    /// Rejeita: tamanho != 11, dígitos todos iguais (000…000, 111…111), DV incorreto.
    /// </summary>
    public static class CpfValidator
    {
        public static bool IsValid(string? cpf)
        {
            if (string.IsNullOrWhiteSpace(cpf)) return false;

            // Strip não-dígitos
            Span<char> digits = stackalloc char[11];
            var idx = 0;
            foreach (var c in cpf)
            {
                if (c < '0' || c > '9') continue;
                if (idx >= 11) return false; // mais que 11 dígitos
                digits[idx++] = c;
            }
            if (idx != 11) return false;

            // Todos iguais (00000000000, 11111111111, ...) — inválidos por convenção
            var first = digits[0];
            var allEqual = true;
            for (var i = 1; i < 11; i++)
            {
                if (digits[i] != first) { allEqual = false; break; }
            }
            if (allEqual) return false;

            // 1º dígito verificador
            var sum = 0;
            for (var i = 0; i < 9; i++) sum += (digits[i] - '0') * (10 - i);
            var d1 = (sum * 10) % 11;
            if (d1 == 10) d1 = 0;
            if (d1 != digits[9] - '0') return false;

            // 2º dígito verificador
            sum = 0;
            for (var i = 0; i < 10; i++) sum += (digits[i] - '0') * (11 - i);
            var d2 = (sum * 10) % 11;
            if (d2 == 10) d2 = 0;
            return d2 == digits[10] - '0';
        }
    }
}
