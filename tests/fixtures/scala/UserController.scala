package com.example.app

import play.api.mvc._

/** A user controller. */
class UserController(val service: UserService) extends Controller {
  def show(id: Long) = Action { request =>
    Ok(service.find(id).toString)
  }

  def list = Action { Ok("list") }
}

trait UserService {
  def find(id: Long): User
}

object UserService {
  def apply(): UserService = new DefaultService()
}

case class User(id: Long, name: String)

object Helpers {
  def format(text: String): String = text.toUpperCase
}
