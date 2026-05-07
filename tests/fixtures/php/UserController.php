<?php
namespace App\Http\Controllers;

use Illuminate\Routing\Controller;

/**
 * Manages users.
 */
#[Route('/users')]
class UserController extends Controller
{
    /**
     * Show a user.
     */
    #[Route('/{id}', methods: ['GET'])]
    public function show(int $id): User
    {
        return User::find($id);
    }

    #[Route('/', methods: ['POST'])]
    public function store(): User
    {
        return new User();
    }
}

interface UserService
{
    public function find(int $id): ?User;
}

trait HasTimestamps
{
    public function touch(): void {}
}

enum Status
{
    case Active;
    case Inactive;
}

function helper(): string
{
    return "x";
}
