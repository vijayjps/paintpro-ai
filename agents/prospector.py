from crewai import Agent


class ProspectorAgent:
    def __init__(self, llm, search_tool=None):
        self.llm = llm

    def create_agent(self):
        return Agent(
            role="Expert Lead Finder",
            goal="Identify potential residential customers who likely need exterior painting services",
            backstory=(
                "You are a seasoned real estate scout specializing in finding homes that could benefit "
                "from professional painting. You use your deep knowledge of residential neighborhoods, "
                "property ages, and local real estate trends to identify older homes, faded exteriors, "
                "or recently-listed properties in target areas."
            ),
            llm=self.llm,
            tools=[],
            verbose=False
        )
