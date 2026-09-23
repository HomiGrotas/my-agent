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

## Goal
Now the agent has a real goal - send a personalized WhatsApp message about the weekly Parashat HaShavua, connecting it to this week's news in Israel.

## Setup
The agent runs as a single task (no chat loop), so everything is configured using environment variables:
* `GEMINI_API_KEY` - the model provider key
* `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` - Meta WhatsApp Cloud API credentials
* `NEWS_API_KEY` - [NewsAPI](https://newsapi.org) key
* `RECIPIENT_PHONE_NUMBER` - who gets the message
* `RABBI` (optional) - whose articles to base the message on (defaults to Rabbi Sacks)

Then run:
```
uv run my-agent
```

## Technology Details
### The agent loop
Remember the loop I wrote by hand in Phase 1? Pydantic AI does it for me - call the model, run the tool, feed the result back, and repeat until the model is done.
The nice part is that the model can now call several tools one after the other (news -> articles -> send), while my original loop supported only a single round of tool calls.

### Tools are just functions
No more hand written JSON schemas! A tool is a regular Python function registered with `@agent.tool_plain`, and Pydantic AI builds the schema from the type hints and the docstring.
> This means the docstring is part of the prompt. A vague parameter description = a model that sends the wrong arguments.

### Model agnostic
The model is just a string, e.g. `'google:gemini-3.5-flash-lite'`. Switching providers or models is a one line change, which solves the coupling problem from Phase 2.
It also turned model choice into a trade-off I can actually tune - capability vs. cost vs. speed.

### Context engineering
There are two ways to give the model knowledge:
* **Inject it into the instructions** - this week's Parasha is fetched from [Sefaria](https://www.sefaria.org) when the process starts and embedded in the system prompt, as every run needs it.
* **Let the model fetch it using a tool** - news and Rabbis' articles, where the model decides what to ask for.

Deciding what goes into the prompt upfront and what the model should retrieve by itself is a big part of building an agent.

### Grounding
LLMs love to make things up, especially when it comes to Torah. So instead of letting the model invent a Dvar Torah, I give it real articles by Rabbis (Sacks, Riskin, Rav Kook, Sivan Rahav-Meir and more) and ask it to draw on them.
The model must also return the source article url, so every message cites where it came from.

The articles are downloaded ahead of time by the scripts in `scripts/` into `res/parashot_articles/`, so the tool only reads local files.
This is a poor man's RAG - lookup by Parasha name instead of semantic search. Real RAG is the next step (see `tasks.md`).

### LLM for creativity, code for structure
At first, the model wrote the whole message. The result? Titles, formatting and links changed every run.
Now the model writes only the creative part (the דבר תורה), and a plain Python template adds the title, the Parasha summary and the link.
> Rule of thumb: let the LLM do judgment and writing, and let code do everything that must be exact.

### Self correcting tools
What happens when the model asks for a Rabbi that doesn't exist? Instead of crashing, the tool raises `ModelRetry`, and the model gets the error message and another chance.
I also added a `list_available_rabbis` tool so the model can discover the valid options by itself.

### System prompt as a spec
The system prompt grew from a single sentence into a real spec:
* A numbered workflow (fetch news -> fetch articles -> write -> send)
* Filters - use news in an optimistic way only, no more than 3 articles
* Defaults - Rabbi Sacks if the user didn't choose one
* Constraints - Hebrew only, message length, no titles or links (code adds them)
* Tone - warm, not preachy, respectful of all Jewish denominations

### Observability
How do you debug an agent? You can't just look at the final output - you need to see what the model decided along the way.
I use [Logfire](https://pydantic.dev/logfire) (`logfire.instrument_pydantic_ai()`) to trace every model call, tool call and its arguments.

### From chatbot to autonomous task
The agent doesn't chat anymore. It gets a single goal ("send to X, based on Rabbi Y") and runs the whole workflow by itself.
Chat is just one way to use an agent - a background task that can be scheduled is another.
