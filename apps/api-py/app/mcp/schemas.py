"""What the model is allowed to pass to each tool: Pydantic models, one per tool.

They do two jobs. Their JSON Schema is what the model is shown as the tool's `parameters`
(native tool calling, ADR 0014), and they validate whatever the model actually sends before any
tool runs. A tool without a model here is never offered to the model, and `confirm` is
deliberately not a field of `create_followup_task`: whether a task is confirmed is decided by the
route from the user's own message, never by the model.
"""

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.mcp.client import ToolSpec


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")  # an argument the schema does not name is an error


class CompanyArgs(_Args):
    company_name: str = Field(min_length=1, description="The company's name, as the user wrote it.")


class SearchArgs(_Args):
    query: str = Field(min_length=1, description="What to look for in the interaction documents.")
    company_name: str | None = Field(
        default=None, description="Only search this company's documents."
    )


class TaskArgs(_Args):
    company_name: str = Field(min_length=1, description="The company the follow-up is for.")
    note: str = Field(min_length=1, max_length=500, description="What the follow-up task is.")


TOOL_ARGS: dict[str, type[_Args]] = {
    "get_company_summary": CompanyArgs,
    "get_open_deals": CompanyArgs,
    "search_documents": SearchArgs,
    "create_followup_task": TaskArgs,
}


def tool_definitions(specs: list[ToolSpec]) -> list[dict]:
    """OpenAI-style function definitions for the tools we have a schema for (descriptions come from
    the tool server; parameters come from our Pydantic models)."""
    definitions = []
    for spec in specs:
        model = TOOL_ARGS.get(spec.name)
        if model is None:
            continue
        schema = model.model_json_schema()
        schema.pop("title", None)
        definitions.append(
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": schema,
                },
            }
        )
    return definitions


def validate_arguments(name: str, arguments: dict) -> dict:
    """Returns the cleaned arguments, or raises ValueError with a message safe to show the model."""
    model = TOOL_ARGS.get(name)
    if model is None:
        raise ValueError(f'There is no tool called "{name}".')
    try:
        return model.model_validate(arguments).model_dump(exclude_none=True)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in error.errors()
        )
        raise ValueError(f"Invalid arguments for {name}: {problems}") from error
