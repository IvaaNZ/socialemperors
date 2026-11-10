![Social Empires](templates/img/logo.png "Social Empires logo")

The Social Empires preservation project by the Social Emperors team.
This project is dedicated to preserving this Flash game so that it's not lost to time.

## Jogar no navegador, com cadastro e aprovação

O acesso principal agora usa **Ruffle auto-hospedado (JavaScript e WebAssembly)** para executar o cliente original no navegador. O jogador não instala Flash, extensão ou navegador especial. Os arquivos do Ruffle estão incluídos em `templates/vendor/ruffle/`, com versão fixa e checksums. O servidor mantém as contas, aprovações e saves; o navegador executa o jogo.

Esta é a opção inicial escolhida em vez de transmitir uma instância do jogo por jogador: evita manter uma sessão gráfica e um fluxo de vídeo no servidor para cada pessoa. Uma reescrita nativa em HTML5 continua sendo uma alternativa de longo prazo, com trabalho muito maior para recriar a interface e o comportamento do jogo.

### Iniciar o projeto

Execute na raiz do repositório, com Python 3.10 ou superior:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/flask --app server create-admin
.venv/bin/python server.py
```

No Windows, substitua `.venv/bin/` por `.venv\Scripts\`. O comando `create-admin` pede nome, e-mail e senha, com confirmação oculta. Não existe administrador ou senha padrão, e a primeira pessoa que se cadastrar não recebe privilégios administrativos.

Abra **http://127.0.0.1:5050/** em um navegador atual. Para manter uma vila antiga na conta do administrador, informe o PID do save durante a criação:

```sh
.venv/bin/flask --app server create-admin --village-id "PID_DO_SAVE"
```

### Fluxo de acesso

1. O jogador cria uma conta em `/register`, com nome, e-mail e senha de 10 a 128 caracteres.
2. A conta fica pendente e ainda não pode carregar o jogo.
3. O administrador entra e abre `/admin` para aprovar ou recusar o cadastro.
4. A aprovação cria e vincula uma vila exclusiva. Depois disso, o login por e-mail e senha abre essa vila diretamente.

O painel também permite suspender o acesso e aprová-lo novamente. A suspensão impede novas requisições do jogo mesmo em uma sessão já aberta e preserva o save. As rotas antigas `/new.html` e `/ruffle.html` levam à vila da conta autenticada. Não há mais uma lista pública de vilas ou escolha de `USERID` na entrada.

### Administração das vilas

No painel de administração, abra **Vilas** ou acesse `/admin/villages`. Cada vila vinculada a uma conta mostra seu jogador, nível e saldos. Em **Gerenciar vila**, o administrador pode alterar o nome, ouro, madeira, comida, pedra, dinheiro do jogo, nível e conclusão do tutorial. Marcar o tutorial como concluído libera a participação nos saques, desde que os outros requisitos sejam atendidos.

Os valores informados **substituem** os saldos atuais. Cada recurso aceita um inteiro de 0 a 1.000.000.000; dinheiro aceita de 0 a 1.000.000. O nível fica entre 1 e 99 na configuração atual. Ao mudar o nível, o servidor ajusta o XP para o início daquele nível, sem conceder recompensas extras. Um nível mantido sem alteração preserva seu XP quando ele já está na faixa correta. Outras ilhas, construções, tropas, inventário e identidade do jogador são preservados.

Toda alteração exige um motivo de 3 a 200 caracteres e registra administrador, data e valores anteriores e novos. Se a vila mudar enquanto o formulário estiver aberto, a gravação é recusada: recarregue os dados antes de editar novamente. Isso impede que um formulário antigo sobrescreva recursos coletados ou transferidos em um saque.

Uma edição administrativa também invalida a chave de uma partida já aberta. O cliente antigo não pode enviar novos comandos até recarregar a vila, evitando que seu XP antigo desfaça uma mudança de nível. A página consulta atualizações enquanto está visível, pausa o jogo ao detectar mudanças e oferece **Atualizar vila**. O login e os formulários continuam disponíveis.

### Dinheiro gratuito e Tesouro

O dinheiro usado para acelerar tarefas e fazer compras especiais continua existindo, com distribuição gratuita para o servidor entre amigos. Abra **Tesouro gratuito** no menu ou acesse `/treasury`. O cliente também foi adaptado para abrir o Tesouro local pelo botão **Dinheiro**, sem checkout ou cobrança; o limite da verificação desse botão está descrito abaixo.

- **Bônus inicial:** 500 de dinheiro, resgatável uma vez por vila vinculada à conta.
- **Recompensa diária:** 100 de dinheiro, com intervalo de 24 horas após o último resgate, medido pelo relógio do servidor. O primeiro resgate diário já está disponível e pode ser feito junto com o bônus inicial.
- Dias sem resgate não acumulam recompensas. O saldo máximo é de 1.000.000; se o bônus ultrapassaria esse limite, o resgate inteiro é recusado e continua disponível para depois.

Zerar o saldo pelo painel, renomear a vila ou reiniciar o servidor não libera um novo bônus inicial. Os resgates são registrados e protegidos contra submissões repetidas, inclusive após falhas de gravação. Eles alteram somente dinheiro, que permanece separado do ouro e não é transferido nos saques. Reabra a vila para carregar o saldo recebido.

Os valores podem ser configurados por `SOCIAL_EMPIRES_INITIAL_CASH` e `SOCIAL_EMPIRES_DAILY_CASH`, ambos inteiros de 1 a 1.000.000. Uma mudança passa a valer nos próximos resgates; ela não recalcula recompensas já entregues.

### Idioma, tamanho e som

O jogo recebe os textos em português do Brasil, incluindo tutorial, menus, missões e nomes de unidades e construções. Os catálogos de tradução ficam em `config/locales/pt-BR-*.json`; o conteúdo original permanece disponível para a lógica interna do servidor. Os arquivos de fontes mantêm seus nomes originais para preservar a compatibilidade com o cliente.

Também há catálogos em espanhol neutro em `config/locales/es-*.json`, com as mesmas chaves dos catálogos em português. Para usá-los, inicie o servidor com `SOCIAL_EMPIRES_LANGUAGE=es`; o idioma vale para todos os jogadores. As quatro artes com texto continuam em português, e o portal web (login, administração, Rivais e Tesouro) ainda não foi traduzido.

Os rótulos gravados dentro do SWF também são traduzidos, incluindo **Próximo**, **Construir** e **Ajudar**. O servidor prepara uma cópia em memória e a reutiliza nas próximas requisições, preservando o SWF original. Quatro artes da interface com texto em inglês foram localizadas com a ferramenta integrada de geração de imagens, preservando suas proporções, seu tamanho em cena e a transparência. Os PNGs, arquivos usados pelo jogo, prompts exatos e checksums estão em [`config/locales/artwork/`](config/locales/artwork/manifest.json).

O jogo já abre preenchendo a aba, sem esconder as abas ou a barra de endereço do navegador. Os controles ficam em um menu que se recolhe automaticamente, fora da imagem do jogo. Abra-o pela lateral para ajustar o som, usar **Restaurar janela** ou ativar **Tela cheia** do navegador. O espaço reservado aos controles permanece estável ao abrir e fechar o menu, evitando que a imagem e as áreas de clique mudem de posição. Em janelas pequenas ou telas na vertical, os controles ocupam uma área abaixo do jogo. A imagem mantém suas proporções.

O controle **Volume** ajusta o áudio de 0 a 100%, e **Silenciar** permite desligá-lo temporariamente. O navegador lembra o volume nas próximas visitas quando o armazenamento local está disponível; cada entrada no jogo começa preenchendo a aba.

### Nome da vila

Abra **Nome da vila** no menu do jogo ou acesse `/village`. O nome pode ter de 2 a 32 caracteres, incluindo espaços e acentos, e é salvo para as próximas visitas. Ele aparece na vila e nas telas de rivais e classificação. O nome do jogador continua independente. Saves antigos que ainda usam o nome padrão `My Empire` ou `My empire` passam a exibir `Meu Império`; nomes personalizados são preservados.

### Rivais, ataques e saques

Abra **Rivais e saques** no menu ou acesse `/rivals`. Os combates dessa tela são **automáticos e resolvidos no servidor**, usando os exércitos e as defesas salvos das duas vilas. Esse fluxo não reproduz a batalha animada do cliente SWF. A tela mostra a força dos dois lados, o saque possível, a classificação e os 20 ataques ou defesas mais recentes da sua vila.

- Só participam jogadores com contas aprovadas, vilas próprias e tutorial concluído. Não é possível atacar a própria vila nem personagens do jogo.
- É preciso ter ao menos uma tropa combatente. A força de cada tropa é `10 × ataque + 5 × defesa + vida`, conforme a configuração do servidor. Contam tropas da raça da vila, soltas ou abrigadas, exceto trabalhadores e curandeiros. A defesa soma também as estruturas da categoria de defesa; o maior total vence, e empates favorecem a defesa.
- Uma vitória transfere **20% de cada recurso disponível** na vila rival: ouro, madeira, comida e pedra, arredondados para baixo. O valor debitado do defensor é o mesmo creditado ao atacante. Dinheiro do jogo não é saqueado; derrotas não transferem recursos.
- Há um intervalo de **15 minutos** entre ataques e de **6 horas** para atacar novamente o mesmo rival. Uma vila saqueada recebe **60 minutos** de proteção.
- A diferença de nível permitida é de até `máximo(3, nível do atacante ÷ 2 arredondado para baixo)`. Vilas ainda em tutorial ficam protegidas.
- Tropas e construções permanecem intactas após o combate. A classificação considera vitórias e usa recursos saqueados e defesas bem-sucedidas como critérios de desempate, sempre a partir dos combates registrados.

Os recursos são atualizados nos saves assim que o saque termina. Uma vila já aberta consulta alterações a cada 15 segundos enquanto a aba está visível, e também ao retornar para ela. Quando há um ataque, edição administrativa ou resgate registrado, o jogo é pausado, o menu recebe um aviso e oferece **Atualizar vila**. Reabra a vila para carregar os saldos atuais no HUD; o cliente original não recebe esses saldos em tempo real.

O saque é protegido contra submissões repetidas e não aceita vitória ou quantidade de recursos informadas pelo navegador. A economia legada, porém, ainda confia em parâmetros do cliente em comandos de compra, coleta, bônus e missões. Esses caminhos podem alterar o exército ou os recursos do próprio jogador indevidamente. Portanto, esta implementação serve para **beta com participantes controlados**; ainda não está pronta para competição pública resistente a trapaças.

### Tutorial e retomada

O progresso do tutorial fica em `privateState.startingTutorialStep`, separado da flag `completed_tutorial`. Ao reabrir a vila, o cliente retoma um ponto seguro: seleções de unidades, ordens de movimento e objetos em colocação são reconstruídos pelas etapas apropriadas. As sete lições iniciais terminam na etapa interna **15**, e a continuação ligada às missões também tem seu progresso salvo. A liberação permanece na etapa **31**, quando começa a última sequência de corte de árvores.

As transições também restauram a entrada do mapa pelo método nativo do jogo. Isso evita o bloqueio de cliques quando uma janela de treinamento ou da loja desaparece enquanto o ponteiro ainda está sobre ela.

Saves antigos sem checkpoint são reconciliados pelos objetivos que já existem no mapa. Uma árvore do tutorial já colhida não precisa reaparecer nem ser cortada novamente; o fluxo continua pela construção. A recuperação altera somente metadados do tutorial e preserva unidades, construções, recursos, XP e nível.

No carregamento, a produção aguarda a inicialização dos aldeões contidos nas construções, inclusive durante o tutorial. Isso evita que depósitos vazios sejam colhidos automaticamente antes de o mapa ficar pronto, desaparecendo e gerando saltos de XP e nível. O servidor também ignora coletas de depósitos naturais sem aldeões ou já removidos; produção regular de moinhos e plantações continua funcionando.

Na sequência final, árvores dos três alvos que já foram colhidas contam como concluídas. A missão de construir uma plantação usa a definição original, com instruções em português e recompensa de 10 moedas de ouro.

Após atualizar o código, reinicie o servidor e recarregue a aba do jogo para receber o cliente corrigido. A cópia original do SWF continua preservada; o servidor prepara a versão com retomada em memória.

### Qualidade visual

O player acompanha a resolução da área do jogo e a densidade de pixels da tela, incluindo telas Retina. A suavização solicita qualidade `16x16`, limitada automaticamente ao que a GPU suporta. As artes dos botões **Construir** e **Dinheiro** usam texturas com quatro vezes a resolução em cada dimensão, com ajuste das coordenadas para manter seu tamanho e suas áreas de clique.

O visual original foi preservado. O acervo ainda contém imagens pequenas: 2.035 miniaturas externas têm 90 × 90 pixels, e o cliente inclui outros bitmaps antigos. A renderização em uma tela HD/Full HD não transforma esses arquivos em artes com detalhes novos. Portanto, o acervo completo ainda não é HD; recuperar mais detalhe nessas imagens exige fontes de maior resolução ou tratamento individual das artes.

### Dados e configuração

As contas e aprovações ficam em `instance/accounts.sqlite3`; a chave persistente das sessões, em `instance/secret_key`. O histórico e o journal de saques ficam em `instance/raids.sqlite3`; alterações administrativas, em `instance/administration.sqlite3`; e resgates gratuitos, em `instance/treasury.sqlite3`. Os saves continuam em `saves/`.

Antes de gravar um save alterado, cada serviço registra no seu journal o estado final completo; um saque registra os dois saves envolvidos. Gravações interrompidas são recuperadas na inicialização e antes de novas alterações, sem duplicar recursos, bônus ou entradas do histórico. Se a recuperação falhar, novas ações ficam bloqueadas até que ela possa ser concluída. Em POSIX, os arquivos e o diretório dos saves são sincronizados em disco antes da confirmação; em Windows, a recuperação cobre interrupções do processo, sem a mesma garantia de sincronização do diretório em queda de energia.

Faça backup de **contas, chave, os três journals e saves juntos**, com o servidor parado para obter um conjunto consistente. Preserve os arquivos auxiliares dos bancos SQLite ou utilize o mecanismo de backup do SQLite. Apagar o banco do Tesouro perde o registro dos bônus e permite que sejam resgatados novamente. Senhas são armazenadas como hashes; não são gravadas em texto puro.

| Variável | Uso |
| --- | --- |
| `HOST` / `PORT` | Endereço e porta de escuta; padrões `127.0.0.1` e `5050`. |
| `SOCIAL_EMPIRES_DATA_DIR` | Diretório alternativo para contas, chave e journals de saques, administração e Tesouro e, por padrão, seu subdiretório `saves/`. |
| `SOCIAL_EMPIRES_SAVES_DIR` | Sobrescreve apenas o diretório dos saves, inclusive para reutilizar saves existentes. |
| `SOCIAL_EMPIRES_INITIAL_CASH` | Bônus inicial gratuito; padrão `500`, inteiro de 1 a 1.000.000. |
| `SOCIAL_EMPIRES_DAILY_CASH` | Recompensa gratuita a cada 24 horas; padrão `100`, inteiro de 1 a 1.000.000. |
| `SOCIAL_EMPIRES_LANGUAGE` | Idioma do jogo para todos os jogadores: `pt-BR` (padrão) ou `es` (espanhol neutro). |
| `SECRET_KEY` | Chave opcional de pelo menos 32 caracteres; mantenha estável entre reinícios. |
| `COOKIE_SECURE=1` | Envia o cookie de sessão somente por HTTPS; use com HTTPS configurado. |

O comando `server.py` inicia um servidor local de desenvolvimento. Para hospedagem pública, configure HTTPS e um servidor WSGI com **um processo e uma thread**, pois o motor legado mantém as vilas em memória. Vários processos independentes podem sobrescrever o progresso uns dos outros.

O cliente resolve os caminhos do Ruffle, dos assets e da API usando a URL pública no navegador, incluindo HTTPS, domínio e porta. O Flask pode receber HTTP do proxy sem gerar downloads HTTP dentro da página HTTPS. O proxy deve preservar o cabeçalho `Host`; não habilite confiança irrestrita em cabeçalhos `X-Forwarded-*` recebidos da internet.

### Erro de carregamento atrás de HTTPS

Se aparecer “Não foi possível baixar os arquivos do jogo deste servidor”, confira o console e a aba Rede do navegador. Antes da correção, o uso de `request.url_root` podia gerar `http://.../vendor/ruffle/ruffle.js` quando o proxy encerrava o HTTPS e encaminhava HTTP ao Flask. O navegador bloqueava esse script como conteúdo misto, sem enviar a requisição ao backend. Os arquivos do Ruffle já estão versionados; nesse caso, reinstalá-los não resolve.

Depois de enviar a correção ao repositório remoto, atualize a instalação existente:

```sh
cd /root/socialemperors
git pull --ff-only
systemctl restart socialempires
```

Recarregue a página com **Ctrl+F5**. Não recrie a conta administrativa nem apague `instance/` ou `saves/` para corrigir esse erro.

### Segurança da hospedagem

O projeto tem aprovação de contas, hashes de senha, CSRF, isolamento de vilas, controles administrativos e limitação de tentativas de login. Isso não torna a configuração de desenvolvimento adequada para exposição pública. Para hospedar:

- Execute um servidor WSGI com um processo e uma thread, usando um usuário de serviço sem privilégios. Não execute como `root` nem publique o servidor de desenvolvimento do Flask. O usuário precisa gravar somente os diretórios de dados e saves.
- Redirecione HTTP para HTTPS no proxy e configure `COOKIE_SECURE=1` no ambiente do serviço. Considere HSTS no proxy depois de confirmar que o domínio funciona exclusivamente por HTTPS.
- Permita acesso à porta do backend somente pelo proxy. Se ambos estiverem na mesma máquina, use loopback; se estiverem em máquinas diferentes, limite a porta no firewall ao IP privado do proxy.
- Limite solicitações de cadastro e login no proxy. O cadastro ainda não tem limitação própria, e o cálculo de hashes pode ocupar o servidor. Sem configuração explícita de proxy confiável, a limitação de login considera o IP do proxy, compartilhado entre jogadores.
- Mantenha o sistema e as dependências atualizados e faça backups consistentes dos dados conforme descrito acima.

O motor legado ainda confia em valores de recursos, XP e compras enviados pelo cliente. Uma conta aprovada pode adulterar esses comandos e afetar outros jogadores pelos saques. **A economia ainda não oferece proteção suficiente contra trapaças para um jogo competitivo público.** Validar recompensas, custos e progressão no servidor exige uma revisão própria; HTTPS e aprovação de contas não resolvem essa limitação. Para um grupo privado, restrinja também o acesso de rede aos participantes enquanto essa revisão não for feita.

### Ruffle e compatibilidade

O Ruffle incluído é o **0.7.1**, com arquivos e licenças de sua distribuição oficial. Para reinstalar exatamente essa versão:

```sh
python3 tools/install_ruffle.py
# Ou, sem rede, com o arquivo oficial previamente baixado:
python3 tools/install_ruffle.py --archive /caminho/ruffle-0.7.1-web-selfhosted.zip
```

O instalador valida o SHA-256 antes de escrever os arquivos. O navegador recebe o runtime e os assets do próprio servidor; não há CDN de runtime ou download automático de assets externos durante a partida.

O cliente continua sendo o SWF original, executado pelo Ruffle; esta alteração não é uma reescrita do jogo em HTML5. O suporte a ActionScript 3 ainda possui limitações. Consulte a [documentação de auto-hospedagem](https://github.com/ruffle-rs/ruffle/wiki/Using-Ruffle#web) e o [estado de compatibilidade](https://ruffle.rs/compatibility).

Para direcionar o dinheiro gratuito, `swf_private_economy.py` altera somente o corpo de 52 bytes do método `Base.gotoCash` na cópia servida do cliente fixado. Checksums validam o bytecode original e a alteração; os demais métodos, fontes e o arquivo SWF original são preservados. A navegação usa o parâmetro `gocash` apontando para `/treasury`, na mesma origem, sem liberar `allowScriptAccess` ao jogo.

### Verificação

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Os testes automatizados cobrem persistência das contas, senhas, aprovação e recusa, CSRF, tentativas de login, vínculo exclusivo com a vila, bloqueio após suspensão, gravação do save e integridade das traduções. Também verificam validação e persistência do nome da vila, regras de saque, conservação dos recursos, submissões repetidas, classificação e recuperação após falhas entre gravações ou durante a sincronização em disco. A administração verifica limites, coerência de nível e XP, revisão de formulários, histórico e preservação do restante da vila; o Tesouro verifica bônus único, intervalo pelo relógio do servidor, limite de saldo e recuperação sem crédito duplicado.

As telas administrativas e o Tesouro pelo menu foram validados em Chromium no desktop e a 390 px. A verificação automatizada do clique no botão **Dinheiro** do SWF ficou inconclusiva no renderizador por software: os popups antigos de notícias também não responderam aos cliques. O acesso ao Tesouro pelo menu está disponível e foi validado.

Também foi testado em Chromium sem extensão: login aprovado, abertura da vila e do tutorial do Arthur, clique para avançar o tutorial, envio de comandos e manutenção de nível/recursos após recarregar. As telas de acesso foram verificadas em desktop e a 320 px; o jogo, em desktop e a 390 px. A falha de download do runtime exibe uma mensagem com opção de tentar novamente.

**Limitações conhecidas:** o acervo original não contém `fx/p.miniFireball2.swf`, que retorna 404; isso não impediu o teste básico da vila. Todas as missões, unidades, efeitos e combinações de navegadores ainda não foram validados. A apresentação inicial do tutorial pode reaparecer até sua conclusão, conforme a lógica existente do jogo.

[![Downloads](https://img.shields.io/github/downloads/AcidCaos/socialemperors/total?label=downloads%40all)](../../releases/latest)
[![Discord](https://img.shields.io/discord/984545703558783016?logo=discord&label=Discord&color=blue)](https://discord.gg/zW5gSbQJBw)

---

## Latest Release

| Version | Release date | Source | Download |
| --- | --- | --- | --- |
| **alpha 0.04a** | September 26, 2025 | :label: [tag](../../releases/tag/0.04a) | :package: [Bundle](../../releases/download/0.04a/social-emperors_0.04a.zip) |

:information_source: For older versions check [this](RELEASES.md).

## Reporting Bugs and Contacting

:speech_balloon: Check our [Discord group](https://discord.gg/zW5gSbQJBw)

:paw_prints: The project [Contributors](../../contributors)

## Legacy releases: How to Install on Windows

As instruções abaixo se referem aos bundles antigos. Para o código atual, use o procedimento de navegador acima.

- Download a flash-compatible browser. :flashlight: **Recommended:** [FlashBrowser](https://github.com/radubirsan/FlashBrowser/releases/latest). Alternatives can be found [here](FLASH.md).
- Download the latest Bundle version from the [Latest Release](#latest-release) section.
- Extract the downloaded zip file to a suitable location.

## Legacy releases: How to Play

- Run the *social-emperors* executable.
- Open your flash browser and navigate to `http://127.0.0.1:5050/`.

:information_source: To play on GNU/Linux check [this page](LINUX.md).

## Tools

:penguin: [Social Empires on GNU/Linux](LINUX.md)

:flashlight: [Flash Continuation](FLASH.md) documentation

## On archives and accessibility to digital heritage

- [Exemption to PCCPSACT](https://www.federalregister.gov/documents/2018/10/26/2018-23241/exemption-to-prohibition-on-circumvention-of-copyright-protection-systems-for-access-control), exemptions to the provision of the Digital Millennium Copyright Act (“DMCA”). 
- [EFGAMP](https://efgamp.eu/), the European Federation of Video Game Archives, Museums and Preservation projects.
- [UNESCO PERSIST Programme](https://unescopersist.org/), helps ensure that digital information can continue to be accessed in the future.
- [The Internet Archive](https://archive.org/), a digital library of Internet sites and other cultural artifacts in digital form.
- [BlueMaxima's Flashpoint](https://bluemaxima.org/flashpoint/), the webgame preservation project.
- [Adobe Flash Player Archive](https://archive.org/download/flashplayerarchive/), the Adobe Inc. archive.org Flash Player Archive.

---

## License [![GPL v3](https://img.shields.io/badge/GPL%20v3-blue)](http://www.gnu.org/licenses/gpl-3.0)

```
Social Empires preservation project.
Copyright (C) 2022  The Social Emperors team
See the GNU General Public License <https://www.gnu.org/licenses/>.
```
