namespace BankMore.ContaCorrente.Application.Services
{
    /// <summary>
    /// Interface para serviço de hash de senhas.
    /// 
    /// Responsabilidades:
    /// - Fazer hash seguro de senhas
    /// - Verificar se uma senha corresponde a um hash armazenado
    /// 
    /// Padrão: Dependency Injection + Strategy Pattern
    /// </summary>
    public interface IPasswordHasher
    {
        /// <summary>
        /// Faz o hash de uma senha com salt.
        /// </summary>
        /// <param name="password">Senha em texto plano</param>
        /// <param name="salt">Salt para aumentar a segurança (previne rainbow tables)</param>
        /// <returns>Hash da senha (string hexadecimal)</returns>
        string HashPassword(string password, string salt);

        /// <summary>
        /// Verifica se uma senha fornecida corresponde ao hash armazenado.
        /// </summary>
        /// <param name="password">Senha em texto plano fornecida pelo usuário</param>
        /// <param name="hashedPassword">Hash armazenado no banco de dados</param>
        /// <param name="salt">Salt usado originalmente para fazer o hash</param>
        /// <returns>true se a senha corresponde, false caso contrário</returns>
        bool VerifyPassword(string password, string hashedPassword, string salt);
    }
}
