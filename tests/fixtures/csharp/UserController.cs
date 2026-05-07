namespace MyApp.Api.Controllers;

using Microsoft.AspNetCore.Mvc;

/// <summary>Manages users via the public API.</summary>
[ApiController]
[Route("api/users")]
public class UserController : ControllerBase
{
    private readonly IUserService _service;

    public UserController(IUserService service)
    {
        _service = service;
    }

    /// <summary>Look up a user by id.</summary>
    [HttpGet("{id}")]
    public async Task<User> GetUser(int id)
    {
        return await _service.FindAsync(id);
    }

    [HttpPost]
    [Authorize]
    public IActionResult CreateUser([FromBody] User u) => Ok(u);
}

public record User(int Id, string Name);

public interface IUserService
{
    Task<User> FindAsync(int id);
}

public enum Status { Active, Inactive }
