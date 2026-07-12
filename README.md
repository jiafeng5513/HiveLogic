<div align=center><img width="100" height="100" src="client/resources/hivelogic_logo.png"/></div>
</br>
<div align=center>HiveLogic</div>
</br>
</br>
</br>
<div align=center><img src="doc/screenshot.png"/></div>


## Develop Environment Setup
1. install with windows package control
    ```powershell
    # installs fnm (Fast Node Manager)
    winget install Schniz.fnm

    # close and restart a new windows shell
    fnm env --use-on-cd | Out-String | Invoke-Expression

    # download and install Node.js
    fnm use --install-if-missing 20

    # verifies the right Node.js version is in the environment
    node -v 

    # verifies the right NPM version is in the environment
    npm -v 

    # optinal: find all available version
    fnm list-remote

    # optinal: find all installed version
    fnm list

    # optinal: install a new version 
    fnm install v22.17.0

    # optinal: select a default version
    fnm default v22.17.0

    # optinal: install nrm to manager npm source
    npm install -g nrm
    # optinal: `nrm ls` to show all avaliable source, `nrm use` to set it
    ```

2. close and restart a new Windows shell, run `npm -v`, it should tell you that the npm is not a valied command or executable, that because the npm env is one-time-drop now. You can try `fnm env --use-on-cd | Out-String | Invoke-Expression` again, and then `npm -v`, and it should work again.

3. to make npm env activate auto start with windows shell, edit the `C:\Users\${username}\Documents\WindowsPowerShell\profile.ps1` which created when install anaconda, edit it as bellow:
    ```powershell
    #region conda initialize
    # !! Contents within this block are managed by 'conda init' !!
    If (Test-Path "C:\ProgramData\anaconda3\Scripts\conda.exe") {
        (& "C:\ProgramData\anaconda3\Scripts\conda.exe" "shell.powershell" "hook") | Out-String | ?{$_} | Invoke-Expression
    }
    #endregion

    #region npm initialize
    fnm env --use-on-cd | Out-String | Invoke-Expression
    #endregion
    ```
4. install vue
    ```shell
    npm i @vue/cli -g
    ```

5. install uv
    ```powershell
    winget install --id=astral-sh.uv -e
    ```

### macOS
1. install Homebrew (if not installed)
    ```bash
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    ```

2. install fnm and Node.js
    ```bash
    # install fnm (Fast Node Manager)
    brew install fnm

    # initialize fnm for current shell session
    eval "$(fnm env --use-on-cd)"

    # download and install Node.js
    fnm use --install-if-missing 20

    # verify Node.js and NPM versions
    node -v
    npm -v

    # optional: list all available remote versions
    fnm list-remote

    # optional: list all installed versions
    fnm list

    # optional: install and set another version
    fnm install 22
    fnm default 22

    # optional: install nrm to manage npm source
    npm install -g nrm
    # optional: `nrm ls` to show all available source, `nrm use` to set it
    ```

3. enable fnm auto-load in zsh
    ```bash
    # append fnm initialization into ~/.zshrc
    echo '' >> ~/.zshrc
    echo '# fnm initialize' >> ~/.zshrc
    echo 'eval "$(fnm env --use-on-cd)"' >> ~/.zshrc

    # reload current shell config
    source ~/.zshrc
    ```

4. install vue
    ```bash
    npm i @vue/cli -g
    ```

5. install uv
    ```bash
    brew install uv
    ```

## Recommended IDE Setup

- [VSCode](https://code.visualstudio.com/) + [ESLint](https://marketplace.visualstudio.com/items?itemName=dbaeumer.vscode-eslint) + [Prettier](https://marketplace.visualstudio.com/items?itemName=esbenp.prettier-vscode) + [Volar](https://marketplace.visualstudio.com/items?itemName=Vue.volar)

## Project Setup

### Install

```bash
$ npm install
```

### Development

```bash
$ npm run dev
```

### Build

```bash
# For windows
$ npm run build:win

# For macOS
$ npm run build:mac

# For Linux
$ npm run build:linux
```

## Referemce
1. [electron-vite](https://cn.electron-vite.org/)
2. [清理npm包](https://juejin.cn/post/6997956167473463327)
3. [element-plus 前端组件库](https://element-plus.org/zh-CN/component/overview.html)
4. [UDF API](./UDF-api.md)
5. [Electron + Vue + Vite + Python + FastAPI](https://github.com/hafiidz/electron-vite-vue-fastapi)
6. [TradingView API Reference](https://www.tradingview.com/charting-library-docs/latest/api/)
7. [charting-library-examples](https://github.com/tradingview/charting-library-examples)
8. [charting-library-demo](https://trading-terminal.tradingview-widget.com/)
9. [free-charting-libraries](https://cn.tradingview.com/free-charting-libraries/)
10. [lightweight-charts](https://github.com/tradingview/lightweight-charts)
11. [Binance WSS API](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams)
12. [CCXT: 跨交易所的交易API封装库，为各种交易所提供统一的上层接口，支持python和js](https://docs.ccxt.com/#/README?id=social)
13. [wondertreader](https://wtdocs.readthedocs.io/zh/latest/)
14. [install-redis-on-linux](https://redis.io/docs/latest/operate/oss_and_stack/install/install-redis/install-redis-on-linux/)
15. [openctp主页](http://www.openctp.cn/)
16. [openctp](https://github.com/openctp/openctp)
17. [KLineChart Pro](https://pro.klinecharts.com/)
18. [klinecharts](https://github.com/klinecharts/KLineChart)
19. [klinecharts](https://klinecharts.com/)
20. [klinecharts](https://github.com/klinecharts/preview)
21. [preview.klinecharts](https://preview.klinecharts.com/)
22. [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis)