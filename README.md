# MitmPilot

MitmPilot is a management and extension platform for [mitmproxy](https://www.mitmproxy.org/), providing a web-based interface and plugin architecture for running, managing, and sharing mitmproxy addons. It transforms mitmproxy from a command-line tool into an extensible service with remote management capabilities.

## Main Features

- **Mitmproxy Integration**: Embedded mitmproxy instance with plugin lifecycle management.
- **Web Interface**: Provides a user-friendly web interface based on FastAPI to manage and monitor addons.
- **Hook Routing**: Flexible hook mechanism, supporting dynamic matching and execution of plugins based on rules.
- **Extensibility**: Designed for easy extension, allowing new features and modules to be added conveniently.

## Quick Start

To get started with MitmPilot, follow these steps:

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/wumode/MitmPilot.git
    cd MitmPilot
    ```

2.  **Setup Environment:**
    ```bash
    # Install uv
    pip install uv
    # Create a virtual environment
    uv venv
    # Activate the virtual environment
    source .venv/bin/activate
    # Install dependencies
    uv pip install -e ".[dev]"
    ```
3.  **Start the frontend project:** [MitmPilot-Frontend](https://github.com/wumode/MitmPilot-Frontend)
4.  **Run the application:**
    ```bash
    python -m app.main
    ```

    The application will be accessible at `http://0.0.0.0:6008`.

## Contributing

Contributions of all forms are welcome, including but not limited to:

- Submitting bug reports
- Contributing code
- Improving documentation

## License

This project is open-sourced under the [GPL-3.0](LICENSE) license.

## Related Projects

The core functionality of MitmPilot is ported from [MoviePilot](https://github.com/jxxghp/MoviePilot)
