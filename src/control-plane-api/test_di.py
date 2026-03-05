from neuroglia.hosting.web import WebApplicationBuilder
from neuroglia.mediation import Mediator

builder = WebApplicationBuilder()
Mediator.configure(builder, ["application.commands"])

for service in builder.services:
    if "RequestScaleUpCommand" in str(service.service_type):
        print(service)
