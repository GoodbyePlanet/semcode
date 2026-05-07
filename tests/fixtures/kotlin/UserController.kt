package com.example.app

import org.springframework.web.bind.annotation.*

/**
 * REST controller for users.
 */
@RestController
@RequestMapping("/users")
public class UserController(private val service: UserService) {

    @GetMapping("/{id}")
    suspend fun getUser(id: Long): User {
        return service.find(id)
    }

    @PostMapping
    fun createUser(user: User): User {
        return user
    }
}

interface UserService {
    fun find(id: Long): User
}

data class User(val id: Long, val name: String)

object Helpers {
    fun format(text: String): String = text.uppercase()
}

@Composable
fun MyView(name: String) {
    Text(text = name)
}
