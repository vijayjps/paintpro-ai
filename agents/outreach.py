from crewai import Agent
from pydantic import BaseModel
from typing import List

class EmailDraft(BaseModel):
    subject: str
    body: str
    attachments: List[str]

class OutreachAgent:
    def __init__(self, llm):
        self.llm = llm

    def create_agent(self):
        return Agent(
            role="Friendly Sales Copywriter",
            goal="Write warm, personalized emails that provide value and build trust",
            backstory="You are a neighborhood-friendly copywriter who helps local businesses connect authentically with homeowners. Your emails feel like helpful advice from a trusted neighbor, not pushy sales pitches. You always include value first and clear calls-to-action.",
            llm=self.llm,
            verbose=False
        )