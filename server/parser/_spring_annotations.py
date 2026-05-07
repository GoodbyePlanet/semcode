from __future__ import annotations

# Shared between Java and Kotlin parsers — both target Spring/JPA on the JVM.

SPRING_STEREOTYPES: dict[str, str] = {
    "RestController": "controller",
    "Controller": "controller",
    "Service": "service",
    "Repository": "repository",
    "Component": "component",
    "Configuration": "configuration",
    "RestControllerAdvice": "exception_handler",
    "ControllerAdvice": "exception_handler",
    "Entity": "entity",
    "MappedSuperclass": "entity",
}

HTTP_METHOD_ANNOTATIONS: dict[str, str | None] = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
    "RequestMapping": None,  # method determined from attributes
}

LOMBOK_ANNOTATIONS: set[str] = {
    "Getter",
    "Setter",
    "Data",
    "Builder",
    "NoArgsConstructor",
    "AllArgsConstructor",
    "RequiredArgsConstructor",
    "Slf4j",
    "ToString",
    "EqualsAndHashCode",
    "Value",
}
