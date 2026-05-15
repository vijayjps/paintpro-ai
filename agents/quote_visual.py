from crewai import Agent


class QuoteVisualAgent:
    def __init__(self, llm):
        self.llm = llm

    def create_agent(self):
        return Agent(
            role="Senior Painting Estimator & Visual Designer",
            goal="Create accurate sample quotes and describe before/after visualizations",
            backstory=(
                "You are a master estimator who has priced thousands of painting jobs. "
                "You understand material costs, labor rates, and can describe compelling "
                "visual concepts to show potential transformations for each home."
            ),
            llm=self.llm,
            tools=[],
            verbose=False
        )
