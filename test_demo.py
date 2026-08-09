"""
Demo test: a realistic, longer conversation to show real compression savings.
"""
import asyncio
from fastmcp import Client

conversation_text = """
user: I'm building a personal finance tracker app. I want to track income, expenses, and savings goals.
assistant: Great project. Let's start with the core data model. You'll need at least three tables: transactions, categories, and goals.
user: What fields should the transactions table have?
assistant: I'd suggest: id, amount, type (income or expense), category_id, date, and an optional description field for notes.
user: Should I use SQLite or a full database like PostgreSQL?
assistant: For a personal app used by one user, SQLite is perfect. It's lightweight, requires no separate server, and is more than fast enough for this scale. PostgreSQL would be overkill unless you're building a multi-user product.
user: Okay, I'll go with SQLite. How should I structure the categories?
assistant: Keep categories simple: id, name, and a type field (income or expense) so you can filter easily. Common expense categories might be groceries, rent, transport, entertainment, and utilities.
user: What about the savings goals feature?
assistant: For goals, track: id, name, target_amount, current_amount, and target_date. You can calculate progress as current_amount divided by target_amount to show a percentage.
user: How should the app calculate my monthly summary?
assistant: Sum all transactions where type is income for the month, then sum all transactions where type is expense for the same month. The difference between those two sums is your net savings for that month.
user: Should I build the UI first or the backend logic first?
assistant: Build the backend logic and data model first. Get transactions, categories, and goals working with real data through a script or command-line interface, then layer the UI on top once the core logic is proven to work correctly.
user: What frontend framework would you recommend for this?
assistant: Since you're already comfortable with Python, a simple option is Streamlit, which lets you build a working UI quickly without needing separate frontend and backend deployments. If you want a more traditional web app, Flask with a basic HTML/CSS frontend is another solid, beginner-friendly option.
"""

async def main():
    client = Client("server.py")
    async with client:
        print("Running slim mode on a realistic, longer conversation...\n")
        result = await client.call_tool(
            "extract_session_state",
            {
                "messages": [{"role": "user", "content": conversation_text}],
                "session_id": "demo-long-conversation",
                "mode": "slim",
                "sentence_count": 5,
            },
        )
        print(result.content[0].text)

if __name__ == "__main__":
    asyncio.run(main())