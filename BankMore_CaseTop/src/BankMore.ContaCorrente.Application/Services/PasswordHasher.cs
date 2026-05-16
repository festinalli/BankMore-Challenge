using System;
using System.Security.Cryptography;
using System.Text;

namespace BankMore.ContaCorrente.Application.Services
{
    /// <summary>
    /// PBKDF2-HMAC-SHA256 com 100.000 iterações, 32-byte hash, 16-byte salt.
    ///
    /// Por que PBKDF2 e não SHA-256 puro:
    /// SHA-256 é hash genérico (rápido) — GPU/ASIC quebra senhas comuns em segundos.
    /// PBKDF2 é deliberadamente lento (key stretching). 100k iter = ~10ms por hash em
    /// CPU moderna, inviabilizando bruteforce em larga escala.
    ///
    /// Por que não Argon2id (estado da arte): exige libsodium/NuGet externa
    /// (Konscious.Security.Cryptography). PBKDF2 é nativo no .NET (RFC 2898),
    /// segue OWASP-aprovado, sem dependência. Pra produção real, migrar pra Argon2id.
    ///
    /// Formato de retorno: "pbkdf2$100000$&lt;saltB64&gt;$&lt;hashB64&gt;" — self-describing
    /// permite mudar iterações/algoritmo sem migração: o verify decodifica o que
    /// está gravado e usa esses parâmetros (não os atuais).
    ///
    /// Compat: hashes legados sem prefixo são tratados como SHA-256 (hex) — verify
    /// reconhece e migra implicitamente. Sprint 5: re-hash on login (upgrade silencioso).
    /// </summary>
    public class PasswordHasher : IPasswordHasher
    {
        private const int Iterations = 100_000;
        private const int HashSize = 32;
        private const int SaltSize = 16;
        private const string Prefix = "pbkdf2";
        private static readonly HashAlgorithmName Algo = HashAlgorithmName.SHA256;

        public string HashPassword(string password, string salt)
        {
            if (string.IsNullOrWhiteSpace(password))
                throw new ArgumentException("Senha não pode ser nula", nameof(password));
            if (string.IsNullOrWhiteSpace(salt))
                throw new ArgumentException("Salt não pode ser nulo", nameof(salt));

            // Salt vem como string (compat com schema antigo). Convertemos pra bytes
            // mas mantemos compatibilidade: salt do `contacorrente.salt` é texto Guid.
            var saltBytes = Encoding.UTF8.GetBytes(salt);
            var hashBytes = Rfc2898DeriveBytes.Pbkdf2(
                Encoding.UTF8.GetBytes(password),
                saltBytes,
                Iterations,
                Algo,
                HashSize);

            return $"{Prefix}${Iterations}${Convert.ToBase64String(saltBytes)}${Convert.ToBase64String(hashBytes)}";
        }

        public bool VerifyPassword(string password, string hashedPassword, string salt)
        {
            if (string.IsNullOrWhiteSpace(password))
                throw new ArgumentException("Senha não pode ser nula", nameof(password));
            if (string.IsNullOrWhiteSpace(hashedPassword))
                throw new ArgumentException("Hash não pode ser nulo", nameof(hashedPassword));
            if (string.IsNullOrWhiteSpace(salt))
                throw new ArgumentException("Salt não pode ser nulo", nameof(salt));

            // Hash novo: prefixed self-describing
            if (hashedPassword.StartsWith(Prefix + "$", StringComparison.Ordinal))
            {
                var parts = hashedPassword.Split('$');
                if (parts.Length != 4) return false;
                if (!int.TryParse(parts[1], out var iters)) return false;
                byte[] storedSaltBytes, storedHashBytes;
                try
                {
                    storedSaltBytes = Convert.FromBase64String(parts[2]);
                    storedHashBytes = Convert.FromBase64String(parts[3]);
                }
                catch (FormatException) { return false; }

                var candidate = Rfc2898DeriveBytes.Pbkdf2(
                    Encoding.UTF8.GetBytes(password),
                    storedSaltBytes,
                    iters,
                    Algo,
                    storedHashBytes.Length);

                return CryptographicOperations.FixedTimeEquals(candidate, storedHashBytes);
            }

            // Legacy: hashes pré-PBKDF2 eram SHA-256(senha+salt) hex lowercased.
            // Mantemos compat — Sprint 5 reescreve no login bem-sucedido.
            var legacy = LegacySha256(password, salt);
            return CryptographicOperations.FixedTimeEquals(
                Encoding.UTF8.GetBytes(legacy),
                Encoding.UTF8.GetBytes(hashedPassword.ToLowerInvariant()));
        }

        private static string LegacySha256(string password, string salt)
        {
            var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(password + salt));
            return Convert.ToHexString(bytes).ToLowerInvariant();
        }
    }
}
