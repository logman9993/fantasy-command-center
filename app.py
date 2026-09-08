"""WSGI entrypoint. Application implementation lives in the fcc package."""
from fcc.application import app

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5050")), debug=False)
