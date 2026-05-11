using System;
using System.Security.Cryptography;
using System.Text;

namespace BankMore.ContaCorrente.Application.Services
{
    /// <summary>
    /// Implementação de hash de senhas usando SHA256.
    /// 
    /// Segurança:
    /// - SHA256 (algoritmo forte)
    /// - Combina senha + salt
    /// - Encoding UTF-8
    /// 
    /// Padrão: Strategy Pattern
    /// </summary>
    public class PasswordHasher : IPasswordHasher
    {
        public string HashPassword(string password, string salt)
        {
            if (string.IsNullOrWhiteSpace(password))
                throw new ArgumentException("Senha não pode ser nula", nameof(password));

            if (string.IsNullOrWhiteSpace(salt))
                throw new ArgumentException("Salt não pode ser nulo", nameof(salt));

            using (var sha256 = SHA256.Create())
            {
                var saltedPassword = password + salt;
                var hashedBytes = sha256.ComputeHash(Encoding.UTF8.GetBytes(saltedPassword));
                return BitConverter.ToString(hashedBytes).Replace("-", "").ToLowerInvariant();
            }
        }

        public bool VerifyPassword(string password, string hashedPassword, string salt)
        {
            if (string.IsNullOrWhiteSpace(password))
                throw new ArgumentException("Senha não pode ser nula", nameof(password));

            if (string.IsNullOrWhiteSpace(hashedPassword))
                throw new ArgumentException("Hash não pode ser nulo", nameof(hashedPassword));

            if (string.IsNullOrWhiteSpace(salt))
                throw new ArgumentException("Salt não pode ser nulo", nameof(salt));

            var newHash = HashPassword(password, salt);
            return newHash.Equals(hashedPassword, StringComparison.OrdinalIgnoreCase);
        }
    }
}
