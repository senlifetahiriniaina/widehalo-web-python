from django.apps import AppConfig


class SimulationConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.simulation"
    label = "simulation"
    verbose_name = "Simulation financière"

    def ready(self) -> None:
        # GW3 (passerelle IA locale d'analyse de donnees) : meme patron que
        # `apps.sales.apps.SalesConfig.ready` — enregistrement du tool
        # `simulation.propose_scenario` dans le registre partage `core.
        # services.data_query_tool_registry` (SIM-8).
        from apps.simulation.services.ai_data_query_registration import (
            register_ai_data_query_tools,
        )

        register_ai_data_query_tools()
