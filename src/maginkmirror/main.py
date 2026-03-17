from typer import Typer

app = Typer()

@app.command()
def main():
    print("Hello from maginkmirror!")

if __name__ == "__main__":
    app()