# cutthebullshit

*[English](README.md) · Português*

Transforma fotos de objetos fotografados sobre uma mesa em recortes prontos para compor: cada objeto separado, mais a
sombra que ele projeta e a luz que ele rebate na mesa, em camadas próprias. Dá para colocá-los sobre qualquer fundo e
eles continuam parecendo ter sido fotografados ali. Feito para stop-motion: uma pasta de frames vira uma sequência
animada.

A partir de uma pasta de fotos da câmera, ele gera:

- **Precomps do After Effects**: um por objeto (um por sequência de stop-motion), com controles de força da sombra,
  força da luz rebatida e expandir / suavizar o matte, mais uma comp por cena com tudo sobre o seu fundo.
- **Camadas PNG**: o objeto com alpha, um passe de sombra (Multiply) e um passe de luz rebatida (Screen), para
  qualquer programa de composição.
- **PNGs de layout**: objeto + sombra + luz achatados num único PNG transparente, para montar layouts rápido.
- **Prévias**: JPEGs e um MP4 de cada objeto sobre o seu fundo, e filmes ProRes 4444 dos stop-motions.
- **Um relatório de QC** que aponta os frames em que o recorte provavelmente deixou parte do objeto de fora.

Roda no macOS (e no [Windows](#windows), suporte novo e ainda não testado numa máquina real) e usa o Photoshop (Select
Subject e Content-Aware Fill) e o After Effects; todo o resto é feito em Python com OpenCV.

Os nomes de menus e comandos do Photoshop e do After Effects estão em inglês, como aparecem nos apps em inglês.

## Como funciona

Para cada foto:

1. **prep**: revela o RAW uma única vez num PNG de 16 bits que mantém o visual da própria câmera.
2. **cleanplate**: o Photoshop encontra o objeto (Select Subject → o matte do objeto) e o apaga
   (Content-Aware Fill → a mesa vazia, o "clean plate").
3. **passes**: comparar a foto com a mesa vazia dá a sombra (onde a foto é mais escura) e a luz rebatida (onde é mais
   clara).
4. **layers / preview / prores**: as camadas PNG, os PNGs de layout, as prévias e os filmes.
5. **aecomps**: monta o projeto do After Effects.

Nada é processado duas vezes: rode a mesma pasta de novo e só o que falta é feito.

## Requisitos

- **macOS** (Apple silicon ou Intel), ou **Windows 10 / 11** (veja [Windows](#windows): escrito para ele, ainda não
  rodado numa máquina Windows).
- **Adobe Photoshop** e **Adobe After Effects**, instalados normalmente pelo Creative Cloud. Testado com as versões
  2026; é usada a versão mais nova instalada de cada um.
- **Python 3.11 ou mais novo.** Se você não tiver, o script de instalação consegue baixar um pelo
  [uv](https://docs.astral.sh/uv/).
- **Espaço em disco:** cerca de 60 MB por foto para os arquivos de trabalho, de preferência num disco rápido.

**Não é preciso nenhum plugin, extensão ou servidor MCP.** A ferramenta roda scripts dentro do Photoshop e do After
Effects do mesmo jeito que *File > Scripts* faria. No macOS ela os entrega pelo AppleScript, que já vem no macOS; no
Windows, pela linha de comando do próprio After Effects e pela interface COM do Photoshop (através do pacote
`pywin32`, instalado para você). Ela só precisa da configuração e das permissões dos passos abaixo.

## Instalação

Estes são os passos para macOS. No Windows, siga a seção [Windows](#windows).

**1. Baixe o código e instale**

```bash
git clone https://github.com/<você>/cutthebullshit
cd cutthebullshit
scripts/install.sh
```

Isso cria um ambiente Python em `.venv` dentro do repositório, instala tudo nele (OpenCV, rawpy, numpy e um ffmpeg,
nada no sistema) e roda a verificação de instalação. Para escolher o lugar ou o Python:
`VENV=~/envs/ctb scripts/install.sh`, `PYTHON=/caminho/para/python3.12 scripts/install.sh`.

O comando fica em `.venv/bin/cutthebullshit`. Para digitar só `cutthebullshit`, coloque a pasta no seu PATH:

```bash
echo 'export PATH="'$PWD'/.venv/bin:$PATH"' >> ~/.zshrc
```

**2. Deixe os scripts do After Effects gravarem arquivos**

No After Effects: *Settings* (*Preferences* nas versões antigas) *> Scripting & Expressions >* ative **Allow Scripts
to Write Files and Access Network**. Os scripts devolvem os resultados num arquivo, então sem isso a etapa do After
Effects não roda. O Photoshop não precisa de nenhuma configuração.

**3. Deixe o seu terminal controlar os apps (Automação do macOS)**

Na primeira vez que a ferramenta fala com o Photoshop ou o After Effects, o macOS pergunta se o seu app de terminal
(Terminal, iTerm, VS Code…) pode controlá-lo. Clique em **OK**. Se você clicou em *Não Permitir*, ou se a pergunta não
apareceu, ative em *Ajustes do Sistema > Privacidade e Segurança > Automação*: dentro do seu app de terminal, ligue o
Adobe Photoshop e o Adobe After Effects. O jeito mais fácil de fazer as duas perguntas aparecerem de uma vez é a
verificação do passo 5.

Só para execuções sem acompanhamento (`cutthebullshit supervise`): adicione também o seu app de terminal em *Ajustes do
Sistema > Privacidade e Segurança > Acessibilidade*. Isso deixa o supervisor fechar as janelas de travamento e de
recuperação que, de outro jeito, bloqueariam os apps durante a noite.

**4. Diga para onde vão os seus arquivos** (opcional num primeiro teste)

Copie as configurações de exemplo e edite as pastas:

```bash
mkdir -p ~/.cutthebullshit
cp cutthebullshit.example.toml ~/.cutthebullshit/config.toml
```

Sem um arquivo de configurações, os arquivos de trabalho vão para `~/cutthebullshit/work` e os resultados para
`~/cutthebullshit/output`. Veja [Configurações](#configurações).

**5. Confira tudo**

Abra o Photoshop e o After Effects e então:

```bash
cutthebullshit doctor --apps
```

Ele confere as configurações, se as pastas de trabalho e de saída aceitam gravação e têm espaço livre, os pacotes
Python e o ffmpeg, se os dois apps foram encontrados, a configuração de scripts do After Effects e a Acessibilidade.
Ele também pede para os dois apps rodarem um script minúsculo, o que dispara as perguntas de Automação do passo 3.
Termina com `ready`, ou com uma lista do que corrigir. `cutthebullshit doctor` sem `--apps` faz as mesmas verificações
sem mexer nos apps.

## Windows

O suporte ao Windows é novo: o código foi escrito para Windows 10 / 11, mas ainda não rodou numa máquina Windows, então
a primeira execução pode precisar de pequenos ajustes. Comece com `cutthebullshit doctor --apps`.

**1. Instale** (no PowerShell):

```powershell
git clone https://github.com/<você>/cutthebullshit
cd cutthebullshit
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

Como o script do macOS, ele cria um `.venv` no repositório, instala tudo nele (no Windows também `pywin32` e
`pywinauto`) e roda a verificação de instalação. `-Venv D:\envs\ctb` e `-Python C:\caminho\para\python.exe` escolhem o
lugar e o Python. O comando fica em `.venv\Scripts\cutthebullshit.exe`. Para digitar só `cutthebullshit`, coloque essa
pasta no PATH do seu usuário:

```powershell
$p = [Environment]::GetEnvironmentVariable("Path", "User")
[Environment]::SetEnvironmentVariable("Path", "$p;$PWD\.venv\Scripts", "User")
```

**2. After Effects:** ative *Allow Scripts to Write Files and Access Network*, como no passo 2 da
[Instalação](#instalação).

**3. Rode tudo como o mesmo usuário.** O Windows não tem permissões de Automação ou Acessibilidade para conceder. Em vez
disso, o Photoshop, o After Effects e a janela do PowerShell precisam rodar todos normalmente, ou todos "como
administrador": o Windows não deixa um programa normal mandar scripts nem clicar num programa elevado.

**4. As configurações** ficam em `%USERPROFILE%\.cutthebullshit\config.toml` (copie `cutthebullshit.example.toml` para
lá). Escreva caminhos do Windows entre aspas simples, porque o TOML lê uma barra invertida dentro de aspas duplas como
escape: `work_dir = 'D:\ctb\work'` (ou use barras normais: `"D:/ctb/work"`).

**5. Confira tudo:** com o Photoshop e o After Effects abertos, `cutthebullshit doctor --apps`.

O que mais muda:

- **Os apps** são procurados em `C:\Program Files\Adobe\Adobe After Effects <ano>` e `...\Adobe Photoshop <ano>`.
  Instalou em outro lugar? Coloque em `after_effects_app` / `photoshop_app` o caminho completo do `AfterFX.exe` /
  `Photoshop.exe`.
- **Caminhos curtos:** o Windows limita caminhos a 260 caracteres, a não ser que os caminhos longos estejam ativados; o
  doctor avisa sobre isso. Deixe as pastas de trabalho e de saída perto da raiz de um disco (`D:\ctb\work`,
  `D:\ctb\output`).
- **Começo rápido:** `.\run_example.ps1 D:\Ensaio\bule-anim` (as mesmas opções do `run_example.sh`).
- **Execuções sem acompanhamento:** `cutthebullshit unattended D:\Ensaio --new-run --log D:\ctb\ensaio.log` numa janela
  do PowerShell deixada aberta; ele mantém o PC acordado.
- **Pastas protegidas:** `~/Dropbox` é `C:\Users\<você>\Dropbox`.

Como os apps são controlados, para quando algo precisar de conserto (tudo em `src/cutthebullshit/apps/_windows.py`): o
After Effects recebe cada script pelo `AfterFX.exe -r`, o Photoshop pelo COM (`Photoshop.Application.DoJavaScript`),
as janelas de travamento são fechadas com o `pywinauto` e apps travados são reiniciados com o `taskkill`.

## Começo rápido

Com o Photoshop e o After Effects abertos (sem trabalho não salvo no After Effects; veja
[After Effects](#after-effects)):

```bash
./run_example.sh ~/Ensaio/bule-anim
```

Isso recorta todas as fotos de `~/Ensaio/bule-anim` e coloca os resultados em `~/Ensaio/bule-anim cutthebullshit`, ao
lado. Mais algumas formas de chamar:

```bash
./run_example.sh ~/Ensaio/bule-anim ~/Desktop/bule-recorte                # escolhe a pasta de saída
./run_example.sh ~/Ensaio/bule-anim ~/Desktop/bule-recorte --bg "#2a4d7a"  # prévia sobre um fundo azul
./run_example.sh ~/Ensaio ~/Desktop/recortes --steps prep,cleanplate,passes,layers,preview,prores   # sem After Effects
```

O [`run_example.sh`](run_example.sh) é só um atalho: usa as configurações de exemplo e coloca os arquivos de trabalho
em `<saída>/_work`. O mesmo com o próprio comando:

```bash
cutthebullshit --work ~/Desktop/recortes/_work --output ~/Desktop/recortes run ~/Ensaio/bule-anim
```

O nome da pasta `bule-anim` importa: uma pasta que termina em `-anim` é um stop-motion (veja abaixo).

## Suas fotos

**Formatos:** qualquer RAW de câmera (`.arw .cr2 .cr3 .nef .dng .raf .orf .rw2` e os outros que o LibRaw lê), ou fotos
já reveladas em TIFF, JPEG ou PNG (usadas como estão).

**Stills e stop-motions:** uma pasta cujo nome termina em `-anim` ou `_anim` é um **stop-motion**. As fotos dela viram
uma sequência, uma foto por frame a 12 fps, e um precomp. **Todas as outras fotos são stills**, cada uma com o seu
precomp, mesmo quando os arquivos estão numerados em ordem. Versões dentro de uma pasta de stop-motion
(`bule-anim/v1`, `bule-anim/v2`) são sequências separadas.

**Uma pasta ou uma sessão inteira:** passe para o `run` uma pasta com fotos, ou qualquer pasta acima de várias. A
partir de uma pasta acima, ele pega todas as pastas chamadas `RAW` (`photo_folder` nas configurações) e ignora tudo o
que estiver dentro de uma pasta chamada `CUT OUT`. Uma sessão organizada típica:

```
Ensaio/
  S01 Cozinha/            <- uma cena: ganha a sua própria comp no After Effects
    bule-anim/v1/RAW/     <- um stop-motion, uma sequência
    colher/RAW/           <- stills
  S02 Jardim/
    ...
```

**Nomes:** as sequências recebem o nome do take. Com o padrão de fábrica, `S01_bule-anim_v1_0003_IMG1234.ARW` é o
frame 3 de `S01_bule-anim_v1`. Fotos cujos nomes não se encaixam (`IMG_1234.CR3`) são numeradas na ordem da pasta, e
o stop-motion então recebe o nome da pasta. O `_frames.csv`, junto dos arquivos de trabalho, lista qual foto virou
qual frame.

## Configurações

As configurações ficam num pequeno arquivo TOML. É usado o primeiro encontrado:

1. o arquivo passado com `cutthebullshit --config ARQUIVO`;
2. `cutthebullshit.toml` na pasta de onde você roda;
3. `~/.cutthebullshit/config.toml`, as suas configurações do dia a dia.

Todas são opcionais. O [`cutthebullshit.example.toml`](cutthebullshit.example.toml) explica cada uma (em inglês).

| configuração | padrão | o que faz |
|---|---|---|
| `work_dir` | `~/cutthebullshit/work` | arquivos de trabalho: fotos reveladas, mattes, passes. O After Effects lê o seu footage daqui, então guarde até coletar o projeto |
| `output_dir` | `~/cutthebullshit/output` | resultados: camadas, layouts, prévias, filmes, o projeto do After Effects |
| `background` | `none` | o fundo das prévias e das comps de cena do After Effects: uma imagem, uma cor (`"#rrggbb"`, `"white"`, `"0.5"`, `"200,190,170"`) ou `"none"` (cinza médio) |
| `photo_folder` | `"RAW"` | nome das pastas com fotos, quando você passa uma pasta acima delas (`""`: qualquer pasta com fotos) |
| `photo_extensions` | todos os RAWs comuns + `.tif .jpg .png` | o que conta como foto |
| `exclude_folders` | `["cut out"]` | pastas nunca processadas (maiúsculas ou minúsculas) |
| `stop_motion_suffixes` | `["-anim", "_anim"]` | finais de nome de pasta que indicam stop-motion |
| `sequence_pattern` | `^(?P<base>.+?_v\d+)_(?P<num>\d+)_` | expressão regular: nome do arquivo → sequência (`base`) e número do frame (`num`) |
| `half_size` | `true` | revela os RAWs na metade da resolução (4× mais rápido, menos ruído; uma foto de 24 MP vira 6 MP) |
| `crop` | nenhum | corte central `[largura, altura]` em pixels da resolução cheia |
| `mirror_root` | nenhum | a pasta da sua sessão cujas subpastas são recriadas na saída (senão, as últimas 2–3 pastas de cada caminho) |
| `source_root` | nenhum | a pasta da sua sessão, para o `cutthebullshit status` |
| `protected` | `["~/Dropbox"]` | pastas onde a ferramenta nunca apaga nada (só adiciona e sobrescreve) |
| `photoshop_app`, `after_effects_app` | o mais novo instalado | ex.: `"Adobe After Effects 2025"` |

`--config ARQUIVO`, `--work PASTA` e `--output PASTA`, colocados antes do comando, substituem as configurações numa
chamada: `cutthebullshit --output ~/Desktop/teste run ~/Ensaio/bule-anim`.

## O que é gerado

Cada rodada ganha uma pasta numerada `RUN NN` tanto na pasta de trabalho quanto na de saída; as pastas abaixo dela
repetem a estrutura da sua sessão.

```
<saída>/RUN 01/
  LAYERS/S01 Cozinha/bule-anim/v1/       bule-anim_v1.0001.png               objeto, com alpha
                                         MULTIPLY_bule-anim_v1.0001.png      sombra (modo Multiply)
                                         SCREEN_bule-anim_v1.0001.png        luz rebatida (modo Screen)
                                         _qc_sheet.jpg, _qc.csv, _qc/        relatório de QC (cutthebullshit qc)
  LAYOUTS/S01 Cozinha/bule-anim/v1/      LAYOUT_bule-anim_v1.0001.png        os três num PNG, para layout
  PREVIEWS/                              PREVIEW_bule-anim_v1.0001.jpg       sobre o seu fundo
                                         PREVIEW_bule-anim_v1.mp4            só stop-motions
  PRORES/S01 Cozinha/bule-anim/v1/       bule-anim_v1.mov                    ProRes 4444 com alpha, só stop-motions
  recorte_precomps.aep                   o projeto do After Effects
  _run.json                              o que cada comando run fez

<trabalho>/RUN 01/S01 Cozinha/bule-anim/v1/RAW/
  bule-anim_v1_beauty.0001.png           a foto revelada (16 bits)
  bule-anim_v1_subject.0001.png          o matte do objeto (Select Subject do Photoshop)
  bule-anim_v1_shadow.0001.png           passe de sombra
  bule-anim_v1_bounce.0001.png           passe de luz rebatida
```

O projeto do After Effects usa os arquivos da pasta de trabalho como footage. Para entregar o projeto a alguém, use
*File > Dependencies > Collect Files* no After Effects.

**Qual rodada?** O `run` continua trabalhando na rodada mais nova que já tem essas fotos (senão, na última rodada),
então rodar uma pasta de novo só completa o que falta. `--new-run` começa uma `RUN NN` nova e processa tudo de novo
nela. `--run 3` escolhe uma. `--force` refaz tudo na rodada usada.

## As etapas

O `cutthebullshit run` faz todas estas, em ordem. Cada uma também é um comando próprio, e `--steps` escolhe só algumas
(`--steps layers,preview`). Toda etapa pula o que já está feito.

| etapa | o que faz | tempo por foto* |
|---|---|---|
| `prep` | revela cada RAW uma vez: sem ruído, metade do tamanho, 16 bits, com o visual da própria câmera (a prévia JPEG dentro do RAW; um visual por sequência, para os stop-motions não piscarem). TIFF / JPEG / PNG são usados como estão | ~3 s |
| `cleanplate` | Photoshop: Select Subject → o matte; Content-Aware Fill sobre o objeto e a sua sombra → a mesa vazia | ~13 s |
| `passes` | sombra e luz rebatida: a foto comparada com a mesa vazia. A mesa vazia é apagada depois (~70 MB por foto) | ~3 s |
| `layers` | as camadas PNG, os PNGs de layout e as prévias JPEG | ~2 s |
| `preview` | um MP4 de cada stop-motion, a partir das prévias | — |
| `prores` | um filme ProRes 4444 com alpha de cada stop-motion (veja abaixo) | — |
| `aecomps` | o projeto do After Effects (veja abaixo) | segundos |

\* Medido num Mac de 8 núcleos com 16 GB de RAM. O `run` mostra uma estimativa por etapa quando começa e aprende a
cada rodada.

Outros comandos:

| comando | o que faz |
|---|---|
| `cutthebullshit qc` | aponta frames cujo recorte provavelmente deu errado (veja [QC](#qc)) |
| `cutthebullshit status --run 1` | para cada objeto da sua sessão (`source_root` nas configurações): quais etapas estão feitas, o que falta |
| `cutthebullshit supervise` / `unattended` | o `run` para trabalhos longos sem acompanhamento (veja [abaixo](#execuções-longas-sem-acompanhamento)) |
| `cutthebullshit doctor` | a verificação de instalação |
| `cutthebullshit <comando> -h` | todas as opções de um comando |

**Opções úteis do `run`:**

- `--bg` define o fundo das prévias e das comps de cena: uma imagem (ajustada à altura, centralizada), uma cor
  (`"#2a4d7a"`, `white`, `grey`, `0.5`, `200,190,170`) ou `none`. Substitui o `background` das configurações. Mudar o
  fundo só renderiza de novo as prévias e remonta as comps de cena.
- `--look linear` revela de forma neutra em vez de imitar o visual da câmera; `--exposure`, `--midtones` e
  `--contrast` ajustam o resultado.
- `--denoise raw|strong|off` (padrão `raw`).
- `--grow 60` define até onde, em volta do objeto, o Photoshop preenche, em pixels.
- `--fps 12` é a taxa de frames dos stop-motions.

As fotos são processadas em paralelo: uma por núcleo de CPU, menos dois, limitado pela RAM para que o Photoshop e o
After Effects fiquem com 6 GB. `--workers N` em `prep`, `passes`, `layers` ou `qc`, rodados sozinhos, define você
mesmo o número.

## After Effects

A etapa `aecomps` monta o `recorte_precomps.aep` na pasta de saída da rodada. Ela precisa do After Effects aberto sem
nada por salvar. Se outro projeto estiver aberto e salvo, ele é fechado. Se houver algo não salvo, a etapa para e pede
para você salvar ou fechar antes. Ela nunca salva por cima do seu trabalho.

**O precomp de cada objeto** contém:

- um null CONTROL; tudo está parentado a ele, então mova-o para mover tudo;
- OBJECT: a foto através do matte;
- MATTE: o matte do Photoshop, mais dois sólidos FIX desligados. Ligue um e desenhe uma máscara nele para adicionar ou
  tirar do objeto;
- SCREEN: a luz rebatida;
- MULTIPLY: a sombra.

**Os controles** ficam na camada do precomp dentro da comp de cena: abra *Essential Properties*. Não precisa abrir o
precomp, e cada cópia dele guarda os seus próprios valores.

| controle | padrão | |
|---|---|---|
| Shadow Opacity | 75 | força da sombra (`--shadow-opacity` muda o padrão) |
| Bounce Light Opacity | 100 | força da luz rebatida (`--bounce-opacity`) |
| Matte Grow / Shrink (px) | 0 | + expande, − encolhe o matte do objeto |
| Matte Softness (px) | 0 | suaviza a borda do matte |

**Comps de cena:** cada pasta de cena (ex.: `S01 Cozinha`) ganha uma comp a 24 fps com todos os seus objetos sobre o
fundo. Os stop-motions seguram cada foto por 2 frames (12 fps).

**Usando um precomp na sua própria comp:** coloque-o sobre o seu fundo e ative **Collapse Transformations** na camada
dele. É isso que deixa as camadas Multiply e Screen de dentro se misturarem com o seu fundo. As comps de cena já vêm
com isso ligado.

O projeto mistura as cores do jeito do Photoshop (16 bpc, sRGB, sem mistura linear). Um projeto master configurado com
mistura linear vai deixar a sombra e a luz com outra cara.

## PNGs de layout

O `LAYOUT_*.png` junta objeto, sombra (a 75%) e luz rebatida num único PNG transparente, para posicionar objetos rápido
em modo Normal em qualquer programa. Uma única camada normal só reproduz Multiply e Screen exatamente sobre uma cor,
então ele é feito para ficar exato sobre cinza médio. Sobre outros fundos, a sombra e a luz mantêm a forma e o tom, mas
saem um pouco mais fortes ou mais fracas: em média 3–5 níveis de 255 na área da sombra. Use o precomp ou as três
camadas PNG no trabalho final.

## QC

```bash
cutthebullshit qc               # todos os objetos da rodada mais nova
cutthebullshit qc --run 2
cutthebullshit qc "<saída>/RUN 02/LAYERS/S01 Cozinha/bule-anim/v1"
```

Ele aponta dois tipos de problema:

- **missed**: parte do objeto ficou fora do matte, como um fio fino, uma ponta ou um pedacinho solto. Fora do objeto
  só deveriam sobrar sombra e luz, que mudam o brilho da mesa, não a cor. Uma mancha claramente colorida ali, com borda
  dura, provavelmente é objeto.
- **jump**: num frame o matte fica bem maior ou menor que nos frames dos dois lados, como quando o Select Subject perdeu
  ou acrescentou um pedaço. Um objeto que entra no quadro ou cresce aos poucos não é problema.

A pasta `LAYERS` de cada objeto recebe:

- `_qc_sheet.jpg`: todos os frames em miniatura, partes perdidas em magenta, frames apontados marcados em vermelho;
- `_qc/…_missed1.jpg`: um close de cada ponto (foto | ponto marcado | recorte);
- `_qc.csv`: uma linha por frame.

Para corrigir um frame, use o *Matte Grow* ou os sólidos FIX no After Effects. Ou refaça o matte com
`cutthebullshit cleanplate --force --frames 3 <pasta de trabalho dele>` e rode os passes e as camadas de novo.

O QC é uma indicação, não um veredito. Uma sombra ou um reflexo muito colorido às vezes é apontado, e uma parte perdida
da mesma cor da mesa não é vista.

## Execuções longas sem acompanhamento

Para uma sessão inteira rodando durante a noite, o `cutthebullshit supervise` roda uma pasta de fotos de cada vez e
cuida dos apps:

- Uma etapa que trava (25 minutos sem nenhuma saída) é interrompida, o app dela é reiniciado e a pasta é tentada de
  novo.
- Antes de cada pasta ele confere se o Photoshop (e, na última etapa, o After Effects) ainda responde. Se não, fecha as
  janelas de diálogo deles ou os reinicia.
- Depois de 3 tentativas falhas, a pasta é marcada como falha. O supervisor ainda monta o que dá para aquela pasta e
  segue em frente.
- O After Effects roda uma vez no final, sobre tudo o que deu certo. `--no-ae` para antes dele.
- A cada 5 minutos ele mostra quanto falta para a pasta e para a rodada inteira.
- O progresso fica em `<saída>/RUN NN/_supervise.json`, então rodar de novo com o mesmo número de rodada continua de
  onde parou. Um resumo das falhas vai para `_supervise_summary.txt`.

Comece com `cutthebullshit unattended`, que mantém o próprio supervisor rodando: se ele parar com um erro, é iniciado de
novo um minuto depois na mesma rodada (até 20 vezes), e o computador é mantido acordado enquanto isso.

```bash
cutthebullshit unattended ~/Ensaio --new-run --log ~/Desktop/ensaio.log
```

Deixe a janela aberta. No Mac você também pode iniciá-lo em segundo plano e acompanhar o log:

```bash
nohup cutthebullshit unattended ~/Ensaio --new-run --log ~/Desktop/ensaio.log > /dev/null 2>&1 &
tail -f ~/Desktop/ensaio.log
```

`--new-run` começa uma `RUN NN` nova uma única vez (os reinícios continuam nela), `--run 3` continua a rodada 3, e
qualquer outra opção do `supervise` (`--no-ae`, `--bg ...`) é repassada.

No macOS, fechar janelas de diálogo precisa da permissão de Acessibilidade do passo 3 da [Instalação](#instalação).
`cutthebullshit supervise --selftest` reinicia os dois apps uma vez para conferir que isso funciona.

## Filmes ProRes

Todo stop-motion com mais de um frame é exportado em ProRes 4444 com alpha, 1920 de largura e 24 fps, cada foto segura
por 2 frames. Mude isso com `--width` e `--hold`. O `run` faz isso automaticamente. Para rodar sozinho:

```bash
cutthebullshit prores --run 1
cutthebullshit prores --run 1 "S02 Jardim" --passes object,multiply,screen --force
```

## Solução de problemas

| problema | solução |
|---|---|
| `Not authorized to send Apple events` (erro -1743), ou os apps nunca respondem | permissão de Automação, passo 3 da [Instalação](#instalação) |
| Etapa do After Effects: "has unsaved changes" | salve ou feche o seu projeto no After Effects e rode de novo; todo o resto já está feito e é pulado |
| A etapa do After Effects não faz nada / não há arquivo de resultado | ative *Allow Scripts to Write Files and Access Network* (passo 2 da [Instalação](#instalação)); feche qualquer janela de diálogo aberta no After Effects |
| O Photoshop dá erro em todos os frames | feche as janelas de diálogo do Photoshop; confira se o disco de memória virtual dele tem espaço livre (*Settings > Scratch Disks*) |
| As fotos não são reveladas, ou têm 0 bytes | fotos no Dropbox / iCloud podem estar só online: deixe a pasta disponível offline |
| `Adobe … not found` | coloque em `photoshop_app` / `after_effects_app` nas configurações o nome do app (no Windows: o caminho completo do `Photoshop.exe` / `AfterFX.exe`) |
| Windows: os apps nunca respondem, ou as janelas de diálogo não fecham | rode o Photoshop, o After Effects e o PowerShell como o mesmo usuário, todos normalmente ou todos como administrador |
| Windows: erros sobre caminhos que não existem | o caminho passa de 260 caracteres: pastas de trabalho / saída mais curtas, ou ative os caminhos longos |
| qualquer outra coisa | `cutthebullshit doctor --apps` |

## Observações

- **Nunca apaga em pastas compartilhadas:** dentro do `~/Dropbox` e de qualquer pasta `protected`, a ferramenta só
  adiciona e sobrescreve arquivos. Ela só apaga os seus próprios arquivos temporários (os TIFFs do Photoshop, as
  imagens da mesa vazia depois dos passes, closes antigos do QC), e só nas pastas de trabalho e de saída.
- O que a ferramenta aprende (tempo por etapa) e os scripts que ela entrega ao After Effects ficam em
  `~/.cutthebullshit/` (`CUTTHEBULLSHIT_HOME` muda o lugar).
- Rodadas feitas por versões antigas, com frames EXR, continuam funcionando depois de `pip install -e ".[exr]"`.
- Tudo o que muda entre macOS e Windows fica em `src/cutthebullshit/apps/`: `_mac.py` (AppleScript) e `_windows.py`
  (`AfterFX.exe -r`, COM, `pywinauto`, `taskkill`). O resto do pipeline é igual nos dois.

```
src/cutthebullshit/   cli.py (o comando), pipeline.py (run), supervise.py, unattended.py, prep.py, cleanplate.py, passes.py,
                      layers.py, preview.py, prores.py, aecomps.py, qc.py, status.py, doctor.py,
                      config.py (configurações), frames.py, eta.py, progress.py,
                      apps/ (controle do Photoshop e do After Effects: o único código que depende do sistema)
scripts/              install.sh (macOS), install.ps1 (Windows)
run_example.sh        uma pasta de fotos, do começo ao fim (run_example.ps1 no Windows)
```
