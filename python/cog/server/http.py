from pathlib import Path
import sys
import time
from typing import Dict, Any

from flask import Flask, send_file, request, jsonify, Response

from ..input import (
    validate_and_convert_inputs,
    InputValidationError,
    get_type_name,
    UNSPECIFIED,
)
from ..model import Model, run_model


class HTTPServer:
    def __init__(self, model: Model):
        self.model = model

    def make_app(self) -> Flask:
        start_time = time.time()
        self.model.setup()
        app = Flask(__name__)
        setup_time = time.time() - start_time

        @app.route("/predict", methods=["POST"])
        @app.route("/infer", methods=["POST"])  # deprecated
        def handle_request():
            start_time = time.time()

            cleanup_functions = []
            try:
                raw_inputs = {}
                for key, val in request.form.items():
                    raw_inputs[key] = val
                for key, val in request.files.items():
                    if key in raw_inputs:
                        return _abort400(
                            f"Duplicated argument name in form and files: {key}"
                        )
                    raw_inputs[key] = val

                if hasattr(self.model.predict, "_inputs"):
                    try:
                        inputs = validate_and_convert_inputs(
                            self.model, raw_inputs, cleanup_functions
                        )
                    except InputValidationError as e:
                        return _abort400(str(e))
                else:
                    inputs = raw_inputs

                result = run_model(self.model, inputs, cleanup_functions)
                run_time = time.time() - start_time
                return self.create_response(result, setup_time, run_time)
            finally:
                for cleanup_function in cleanup_functions:
                    try:
                        cleanup_function()
                    except Exception as e:
                        sys.stderr.write(f"Cleanup function caught error: {e}")

        @app.route("/ping")
        def ping():
            return "PONG"

        @app.route("/help")
        def help():
            args = {}
            if hasattr(self.model.predict, "_inputs"):
                input_specs = self.model.predict._inputs
                for name, spec in input_specs.items():
                    arg: Dict[str, Any] = {
                        "type": get_type_name(spec.type),
                    }
                    if spec.help:
                        arg["help"] = spec.help
                    if spec.default is not UNSPECIFIED:
                        arg["default"] = str(spec.default)  # TODO: don't string this
                    if spec.min is not None:
                        arg["min"] = str(spec.min)  # TODO: don't string this
                    if spec.max is not None:
                        arg["max"] = str(spec.max)  # TODO: don't string this
                    if spec.options is not None:
                        arg["options"] = [str(o) for o in spec.options]
                    args[name] = arg
            return jsonify({"arguments": args})

        return app

    def start_server(self):
        app = self.make_app()
        app.run(host="0.0.0.0", port=5000)

    def create_response(self, result, setup_time, run_time):
        if isinstance(result, Path):
            resp = send_file(str(result))
        elif isinstance(result, str):
            resp = Response(result, mimetype="text/plain")
        else:
            resp = jsonify(result)
        resp.headers["X-Setup-Time"] = setup_time
        resp.headers["X-Run-Time"] = run_time
        return resp


def _abort400(message):
    resp = jsonify({"message": message})
    resp.status_code = 400
    return resp