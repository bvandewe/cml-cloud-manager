import inspect

from application.commands.worker.request_scale_up_command import RequestScaleUpCommandHandler

sig = inspect.signature(RequestScaleUpCommandHandler.__init__)
for name, param in sig.parameters.items():
    if name == "self":
        continue
    print(f"{name}: {param.annotation} (type: {type(param.annotation)})")
