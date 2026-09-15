import openai
LLM_API_BASE = "http://192.168.3.11:8088/v1"
llm_client = openai.Client(base_url=LLM_API_BASE, api_key="EMPTY")
response = llm_client.chat.completions.create(
                model="default",
                messages = [{'role': 'user', 'content': "describe yourself"}],
                temperature=0.8,
                max_tokens=1024,
                extra_body={
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
ai_response = response.choices[0].message.content
print(ai_response)