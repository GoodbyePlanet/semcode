# Manages users in the public API.
class UsersController < ApplicationController
  before_action :authenticate
  has_many :posts

  # GET /users/:id
  def show
    @user = User.find(params[:id])
    render json: @user
  end

  def self.create_default
    User.new(name: "anon")
  end
end

class User < ApplicationRecord
  validates :email, presence: true
  has_many :posts
end

module Helpers
  def self.format(text)
    text.upcase
  end
end
