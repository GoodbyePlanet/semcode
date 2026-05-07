#include <stdio.h>

/** Cartesian point. */
typedef struct Point {
    int x;
    int y;
} Point;

enum Color { RED, GREEN, BLUE };

union Variant {
    int i;
    float f;
};

typedef int Id;

/** Add two integers. */
int add(int a, int b) {
    return a + b;
}

static int helper(int n) {
    return n * 2;
}
