-- Utility module.

-- Greets the world.
function greet(name)
    return "hello " .. name
end

-- A local helper.
local function helper()
    return 42
end

local M = {}

function M.add(x, y)
    return x + y
end

function M:method(x)
    return x * 2
end

return M
