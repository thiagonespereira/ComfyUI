"""
Launch ComfyUI with a Gradio wrapper for easy access in Google Colab or locally.

Usage:
  Local:   python run_with_gradio.py
  Colab:   Run in a cell; the ComfyUI UI will appear in the Gradio interface.

The script starts the ComfyUI server in the background, then launches a Gradio app
that embeds the ComfyUI UI (or shows the Colab proxy link when running in Colab).
"""

from __future__ import annotations

import os
import sys
import threading
import time

# ComfyUI root = directory containing this script (so server runs "in place")
COMFYUI_ROOT = os.path.dirname(os.path.abspath(__file__))

# Sanitize argv before ComfyUI parses it.
# In Jupyter/Colab, sys.argv contains: ["colab_kernel_launcher.py", "-f", "<kernel-connection.json>"]
# (or similar). ComfyUI's argparse does not know "-f" and exits with "unrecognized arguments".
# Replace argv with a minimal set so the server thread never sees Jupyter's args.
def _argv_for_comfy():
    base = [sys.argv[0]] if sys.argv else ["python"]
    if "--base-directory" not in base:
        base += ["--base-directory", COMFYUI_ROOT]
    if "--listen" not in base:
        base += ["--listen", "0.0.0.0"]
    if "--disable-auto-launch" not in base:
        base += ["--disable-auto-launch"]
    return base

if "-f" in sys.argv or "ipython" in sys.modules:
    sys.argv[:] = _argv_for_comfy()
else:
    if "--listen" not in sys.argv:
        sys.argv += ["--listen", "0.0.0.0"]
    if "--disable-auto-launch" not in sys.argv:
        sys.argv += ["--disable-auto-launch"]

# ComfyUI port (must match comfy/cli_args.py default)
COMFYUI_PORT = 8188
COMFYUI_URL_LOCAL = f"http://127.0.0.1:{COMFYUI_PORT}"


_server_start_error: list[BaseException] = []  # shared so main() can report it


def _run_comfyui_server():
    """Run the ComfyUI server in the current thread (for use in a daemon thread)."""
    global _server_start_error
    _server_start_error.clear()
    try:
        # Run from ComfyUI root so imports and paths resolve correctly (e.g. in Colab)
        os.chdir(COMFYUI_ROOT)
        if COMFYUI_ROOT not in sys.path:
            sys.path.insert(0, COMFYUI_ROOT)

        import main

        event_loop, _, start_all = main.start_comfyui()
        event_loop.run_until_complete(start_all())
    except BaseException as e:
        _server_start_error.append(e)
        raise


def _wait_for_server(timeout: int = 120, interval: float = 1.0) -> bool:
    """Return True when the ComfyUI server responds, or False on timeout."""
    import urllib.request

    # Try both; some environments resolve only one
    urls_to_try = (COMFYUI_URL_LOCAL, f"http://localhost:{COMFYUI_PORT}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for url in urls_to_try:
            try:
                req = urllib.request.Request(url)
                urllib.request.urlopen(req, timeout=2)
                return True
            except Exception:
                pass
        time.sleep(interval)
    return False


def _get_comfyui_url() -> str:
    """Return the URL to use for ComfyUI in the Gradio iframe (Colab proxy or local)."""
    try:
        from google.colab.output import eval_js
        url = eval_js("google.colab.kernel.proxyPort(" + str(COMFYUI_PORT) + ")")
        if url:
            return url
    except Exception:
        pass
    return COMFYUI_URL_LOCAL


def _expose_colab_port() -> None:
    """When in Colab, expose ComfyUI port so the proxy URL works in the Gradio iframe."""
    try:
        from google.colab import output
        output.serve_kernel_port_as_window(COMFYUI_PORT, path="/")
    except Exception:
        pass


def main() -> None:
    print("Starting ComfyUI server in the background...")
    server_thread = threading.Thread(target=_run_comfyui_server, daemon=True)
    server_thread.start()

    if not _wait_for_server():
        msg = (
            "ComfyUI server did not become ready in time. "
            "Check the console for errors."
        )
        if _server_start_error:
            err = _server_start_error[0]
            msg += f"\n\nServer thread failed with: {type(err).__name__}: {err}"
        raise RuntimeError(msg)
    print("ComfyUI server is ready.")

    in_colab = "google.colab" in sys.modules
    if in_colab:
        _expose_colab_port()
    comfy_url = _get_comfyui_url()

    try:
        import gradio as gr
    except ImportError:
        print("Gradio is not installed. Install with: pip install gradio")
        print(f"ComfyUI is running at: {comfy_url}")
        return

    with gr.Blocks(
        title="ComfyUI",
        theme=gr.themes.Soft(),
        css="""
          .comfy-iframe { width: 100%; height: calc(100vh - 120px); min-height: 600px; border: none; border-radius: 8px; }
        """,
    ) as app:
        gr.Markdown("# ComfyUI")
        if in_colab:
            gr.Markdown(
                "ComfyUI is running below. If the iframe does not load, "
                "use the **Open in new tab** link from the Colab cell output."
            )
        gr.HTML(
            f'<iframe class="comfy-iframe" src="{comfy_url}" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>'
        )

    # In Colab, launch with share=False and show in cell; locally you may want share=True for a public link
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=bool(__import__("os").environ.get("GRADIO_SHARE", "").lower() in ("1", "true", "yes")),
        inbrowser=not in_colab,
    )


if __name__ == "__main__":
    main()
