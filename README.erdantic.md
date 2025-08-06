# Installing erdantic (on macOS)

```shell
brew install graphviz
uv add erdantic --dev --config-settings="--global-option=build_ext" \
            --config-settings="--global-option=-I$(brew --prefix graphviz)/include/" \
            --config-settings="--global-option=-L$(brew --prefix graphviz)/lib/"
```
