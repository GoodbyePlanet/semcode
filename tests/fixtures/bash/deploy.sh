#!/bin/bash
# Deployment helper script.

# Print a greeting.
greet() {
    echo "hello $1"
}

# Add two numbers.
function add() {
    echo $(( $1 + $2 ))
}

greet "world"
