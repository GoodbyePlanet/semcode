#' Compute the sum of two numbers.
add <- function(x, y) {
    x + y
}

#' A simple helper.
helper <- function() 42

setClass("Point", representation(x = "numeric", y = "numeric"))

setGeneric("describe", function(x) standardGeneric("describe"))
