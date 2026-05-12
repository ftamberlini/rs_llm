import os
import json
import time
import argparse
import pandas as pd
from datetime import datetime
from typing import Literal
from pydantic import BaseModel, field_validator
from dotenv import load_dotenv
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIChat
from agno.models.deepseek import DeepSeek
from agno.models.google import Gemini
from prompt.crew_search import description, instructions


class PersonData(BaseModel):
    IMDb_ID: str
    Name: str
    Birthday: str
    Gender: Literal["MALE", "FEMALE", "UNKNOWN"]
    Race: Literal["WHITE", "BLACK", "MIXED-RACE", "ASIAN", "INDIGENOUS", "UNKNOWN"]
    Nationality: str
    Birthplace: str
    Religion: Literal[
        "CHRISTIANITY - CATHOLIC",
        "CHRISTIANITY - PROTESTANT",
        "CHRISTIANITY - ORTHODOX",
        "SPIRITISM",
        "AFRICAN TRADITIONAL RELIGIONS",
        "JUDAISM",
        "ISLAM",
        "BUDDHISM",
        "NEW EASTERN RELIGIONS",
        "OTHER RELIGIOSITIES",
        "NO RELIGION",
        "MULTIPLE BELONGINGS",
        "UNKNOWN",
    ]
    Ethnicity: str

    @field_validator("IMDb_ID")
    @classmethod
    def imdb_id_lowercase(cls, v: str) -> str:
        return v.lower()


MODELS = {
    "claude": lambda: Claude(id="claude-sonnet-4-6"),
    "openai": lambda: OpenAIChat(id="gpt-4.1-mini"),
    "deepseek": lambda: DeepSeek(id="deepseek-v4-pro"),
    "gemini": lambda: Gemini(id="gemini-2.0-flash"),
}


class AgentBatchProcessor:
    def __init__(self, model_name):
        self.agent = Agent(
            model=MODELS[model_name](),
            description=description,
            instructions=[instructions],
            output_schema=PersonData,
        )

    def process_single_query(self, query, max_retries=3):
        for attempt in range(max_retries):
            try:
                response = self.agent.run(query)
                return response.content.model_dump_json()
            except Exception as e:
                if attempt == max_retries - 1:
                    print(f"Failed after {max_retries} attempts: {str(e)}")
                    return f"Error: {str(e)}"
                time.sleep(2 ** attempt)

    def process_batch(self, input_file, output_file, delay=1, batch_size=50, sep=",", limit=None):
        df = pd.read_csv(input_file, sep=sep)
        id_col, name_col = df.columns[0], df.columns[1]

        if os.path.exists(output_file):
            previous = pd.read_csv(output_file, sep="|")
            df["RESPOSTA"] = previous.get("RESPOSTA", "")
            df["STATUS"] = previous.get("STATUS", "")
            already_done = (df["STATUS"] == "success").sum()
            print(f"Resuming: {already_done} queries already processed.")
        else:
            df["RESPOSTA"] = ""
            df["STATUS"] = ""

        pending = df[df["STATUS"] != "success"]
        if limit is not None:
            pending = pending.head(limit)

        print(f"Queries to process: {len(pending)}")
        processed = 0

        for i in range(0, len(pending), batch_size):
            batch = pending.iloc[i:i + batch_size]

            for idx, row in batch.iterrows():
                query = "\t".join(str(v) for v in row[[id_col, name_col, df.columns[2]]].values)
                try:
                    response = self.process_single_query(query)
                    df.at[idx, "RESPOSTA"] = response
                    df.at[idx, "STATUS"] = "success"
                    processed += 1
                    print(f"Processed {processed}/{len(pending)}")
                except Exception as e:
                    df.at[idx, "STATUS"] = f"error: {str(e)}"
                    print(f"Error on query {idx + 1}: {str(e)}")

                time.sleep(delay)

            out = df[[id_col, name_col, "RESPOSTA", "STATUS"]]
            out.to_csv(output_file, index=False, sep="|")
            print(f"Saved batch results up to query {i + len(batch)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("type", choices=["cast", "director", "writer"], help="Input file type")
    parser.add_argument("--model", choices=list(MODELS.keys()), default="claude", help="LLM provider")
    parser.add_argument("--limit", type=int, default=None, help="Max number of queries to process")
    args = parser.parse_args()

    load_dotenv()

    processor = AgentBatchProcessor(model_name=args.model)

    date_str = datetime.now().strftime("%Y%m%d")
    output_file = f"data/result_{args.type}_{args.model}_{date_str}.csv"

    processor.process_batch(
        input_file=f"data/{args.type}.tsv",
        output_file=output_file,
        sep="\t",
        delay=1,
        batch_size=100,
        limit=args.limit,
    )
