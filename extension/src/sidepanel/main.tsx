import { render } from "preact";
import "~panel/index.css";
import "./sidepanel.css";
import { App } from "./App";

render(<App />, document.getElementById("app")!);
