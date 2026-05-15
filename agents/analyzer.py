from crewai import Agent
from pydantic import BaseModel
from typing import List

class HomeAnalysis(BaseModel):
    condition: str
    color_suggestions: List[str]
    issues: List[str]
    scope: str

class AnalyzerAgent:
    def __init__(self, llm):
        self.llm = llm

    def create_agent(self):
        return Agent(
            role="Professional Painting Inspector & Color Consultant",
            goal="Analyze home exteriors/interiors from photos or descriptions and provide expert recommendations",
            backstory="You are a certified painting contractor with 15+ years experience. You can assess paint condition, identify problems, and suggest optimal color schemes that enhance curb appeal and property value.",
            llm=self.llm,
            verbose=False
        )