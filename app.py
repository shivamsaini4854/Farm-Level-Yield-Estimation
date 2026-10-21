"""Development launcher and WSGI entry point."""

from farm_yield.web import app


if __name__ == '__main__':
    app.run(debug=False)
