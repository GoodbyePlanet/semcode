//! Crate-level docs.

use serde::{Deserialize, Serialize};

/// A user record.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct User {
    pub id: u64,
    pub name: String,
}

/// Authentication trait.
pub trait Authenticator {
    fn authenticate(&self, token: &str) -> bool;
}

pub enum Status {
    Active,
    Inactive,
}

pub type UserId = u64;

impl User {
    /// Creates a brand new user.
    pub fn new(name: String) -> Self {
        Self { id: 0, name }
    }

    pub async fn fetch(id: UserId) -> Result<Self, String> {
        Ok(Self::new("anon".into()))
    }
}

#[get("/users/{id}")]
pub async fn get_user(id: UserId) -> Json<User> {
    Json(User::new("hello".into()))
}

#[post("/users")]
pub async fn create_user(body: Json<User>) -> Json<User> {
    body
}

pub fn helper() -> i32 {
    42
}
