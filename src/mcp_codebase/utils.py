from langchain_core.messages import (
    AIMessage,
    FunctionMessage,
    HumanMessage,
    ToolMessage,
)


def format_response(response):
    """
    Format the response from the server for better readability.
    """

    formatted_response = ""
    
    for i, message in enumerate(response["messages"]):
        formatted_response += "\n" + f"\nMessage {i + 1} - Type: {type(message).__name__}"
        formatted_response += "\n" + "-" * 50

        if isinstance(message, HumanMessage):
            formatted_response += "\n" + f"User Input: {message.content}"

        elif isinstance(message, AIMessage):
            formatted_response += "\n" + f"AI Response: {message.content}"
            if message.tool_calls:
                formatted_response += "\n" + "Tool Calls:"
                for tool_call in message.tool_calls:
                    formatted_response += "\n" + f"  Tool Name: {tool_call['name']}"
                    formatted_response += "\n" + "  Arguments:"
                    formatted_response += "\n" + str(tool_call['args'])

        elif isinstance(message, ToolMessage):
            formatted_response += "\n" + f"Tool Response from {message.tool_call_id}:"
            formatted_response += "\n" + f"  Content: {message.content}"

        elif isinstance(message, FunctionMessage):
            formatted_response += "\n" + "Function Response:"
            formatted_response += "\n" + f"  Name: {message.name}"
            formatted_response += "\n" + f"  Content: {message.content}"

        else:
            formatted_response += "\n" + "Other Message:"
            formatted_response += "\n" + message

        formatted_response += "\n" + "-*-" * 60

    return formatted_response