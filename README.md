# Phase 1
A simple agent project - all chat implementations are hand written

## Goal
This project aims to create a simple agent, without a specific goal, as I wanted to get experience with building agents.
I didn't use any agent framework, as I wanted to understand the inner workings of an agent.

## Setup
### Local model setup
You can set it up by following these steps:
1. Install Ollama using  [Ollama website](https://ollama.com/download)
2. Choose a model from the [Ollama model list](https://ollama.com/models) and download it using the command:
   ```
   ollama pull <model_name>
   ```
3. Run the ollama server using the command:
   ```
   ollama serve
   ```
This will run the server on `http://localhost:11434` by default.
I chose to run [llama3.2:latest](https://ollama.com/library/llama3.2) which has 3B parameters, and a context window of 128K tokens.

### Remote model setup
If you want to use a remote model, you should check the documentation of the model provider you want to use, and set up the connection accordingly.
You will need to provide the necessary credentials and endpoint information, which might lead to code changes.

## Technology Details
### System prompt
> A system prompt is a hidden foundational instruction given to an AI model that sets its role, tone, and behavioral boundaries before a conversation even begins. While you write user prompts to ask specific questions, the system prompt acts as the AI's permanent "operating manual" throughout the chat session. It dictates crucial rules, such as forcing the model to speak in a specific format or preventing it from sharing sensitive data. Ultimately, it ensures the AI remains safe, on-topic, and consistent, regardless of what the user inputs
I used gemini to create a system prompt and I modified it to fit my needs. The system prompt is located in `system_prompt.md`.

I used markdown as it structures data clearly for the AI, making instructions much easier for the model to follow.

### OpenAI Python package
Hey! Why did we use openai python package if we are using a local model?
As ollama is compatible with the OpenAI API, we can use the openai python package to interact with the local model.

### Context window
We currently save the conversation in memory, but it's suggested in prod agents to consider another storage method.

# Phase 2
## The problem
As I run a local LLM model (llama 3.2), I encountered a huge difficulty - the model isn't smart enough.

## The Solution
checkout the branch test/gemini, where I implemented the agent using Google AI sdk.
But, is it the best solution? Nope- Using Google Sdk couples me only to gemini models!

So, I need to research solutions, such as LangGraph and Pydantic AI.
* LangGraph - An expansive, feature-rich framework designed for rapid prototyping and complex orchestration
* Pydantic AI - A lean, type-safe Python toolkit built for production reliability

# Phase 3 - building an AI agent using Pydantic AI
