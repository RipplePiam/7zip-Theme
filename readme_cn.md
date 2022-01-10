# 7zip Theme

[TOC]

---

## :question: 这是用来干什么的 ?

这个仓库收集制作了一些 Windows 系统下的压缩文件图标，以及专门用于 [7-zip](https://www.7-zip.org/) 软件的工具栏的替换图标。

众所周知，7-zip 是一款开源免费且高质量的压缩/解压缩软件。然而当人们循着名声安装好 7-zip ，准备大呼过瘾的时候，却发现 7-zip 为了究极小巧而特意设计的工具栏图标和文件夹图标，好像并不能满足自己的美感。我们看看这些原生图标，:arrow_down: :arrow_down: :arrow_down: ，好像是差点意思。

<img src="preview/original_toolbar.png" alt="original_toolbar" style="zoom:80%;" /> <img src="preview/Showtest_FiletypeIcon.png" alt="filetypeIcons" style="zoom:67%;" /> 

所以，这个世界上有很多爱美的人制作了他们认为好看的图标，如果你也喜欢，你可以从下方找到对应的资源，及其使用方法！:clap: :clap: :clap: 



## :astonished: 如何使用 ？





---



## 1. 图标预览及下载

### 1.1 文件图标

> 每个文件图标组的每个 ico 格式图标，都复合包含了 256x256, 64x64, 48x48, 32x32, 24x24, 20x20, 16x16 共 7 中大小的图标。
>
> 部分图标还提供 PSD 格式的设计文件。

#### 1.1.01 Windows 10 Blue

<img src="./preview/filetype/Windows%2010%20Blue.jpg" alt="Windows 10 Blue" style="zoom:80%;" /> 

[Download This Icon Group](./Filetype/Windows%2010%20Blue.zip) 

#### 1.1.02 Windows 10 Default by_d93yxyk

<img src="./preview/filetype/Windows%2010%20Default%20by_d93yxyk.jpg" alt="Windows 10 Default by_d93yxyk" style="zoom:80%;" /> 

[Download This Icon Group](./Filetype/Windows%2010%20Default%20by_d93yxyk.zip) 

#### 1.1.03 7-Zip Original filetype

<img src="./preview/filetype/7-Zip%20Original%20filetype.jpg" alt="7-Zip Original filetype" style="zoom:80%;" /> 

[Download This Icon Group](./Filetype/7-Zip%20Original%20filetype.zip) 

### 1.2 工具栏图标

> 每个工具栏图标组，含有 48x36 和 24x24 两组图标，并且包含 theme.ini 文件，可用于 [7-zip Theme Manager (7zTM)](http://www.7ztm.de/) 软件。

#### 1.2.01 Gion

<img src="./preview/toolbar/Gion.jpg" alt="Gion" style="zoom:80%;" /> 

[Download This Icon Group](./Toolbar/Gion.zip) 

#### 1.2.02 Glyfz 2016

<img alt='Glyfz 2016' src="./preview/toolbar/Glyfz%202016.jpg" width="430" style="zoom:80%;" > 

[Download This Icon Group](./Toolbar/Glyfz%202016.zip) 

#### 1.2.03 Nuvola

<img src="./preview/toolbar/Nuvola.jpg" alt="Nuvola" style="zoom:80%;" /> 

[Download This Icon Group](./Toolbar/Nuvola.zip) 

#### 1.2.04 Office 2013_by_d93yyju

<img src="./preview/toolbar/Office%202013_by_d93yyju.jpg" alt="Office 2013_by_d93yyju" style="zoom:80%;" /> 

[Download This Icon Group](./Toolbar/Office%202013_by_d93yyju.zip) 

#### 1.2.05 Pure

<img src="./preview/toolbar/Pure.jpg" alt="Pure" style="zoom:80%;" /> 

[Download This Icon Group](./Toolbar/Pure.zip) 

#### 1.2.06 Windows 10 Blue

<img src="./preview/toolbar/Windows%2010%20Blue.jpg" alt="Windows 10 Blue" style="zoom:80%;" /> 

[Download This Icon Group](./Toolbar/Windows%2010%20Blue.zip) 

#### 1.2.07 Windows 10 Default

<img src="./preview/toolbar/Windows%2010%20Default.jpg" alt="Windows 10 Default" style="zoom:80%;" /> 

[Download This Icon Group](./Toolbar/Windows%2010%20Default.zip) 

#### 1.2.08 Windows 10 by c3powen d9z0bsg

<img src="./preview/toolbar/Windows%2010%20by%20c3powen%20d9z0bsg.jpg" alt="Windows 10 by c3powen d9z0bsg" style="zoom:80%;" /> 

[Download This Icon Group](./Toolbar/Windows%2010%20by%20c3powen%20d9z0bsg.zip) 

#### 1.2.09 Oxygen 2

<img src="./preview/toolbar/Oxygen%202.jpg" alt="Oxygen 2" style="zoom:80%;" /> 

[Download This Icon Group](./Toolbar/Oxygen%202.zip) 

#### 1.2.10 Oxygen 4

<img src="./preview/toolbar/Oxygen%204.jpg" alt="Oxygen 4" style="zoom:80%;" /> 

[Download This Icon Group ](./Toolbar/Oxygen%204.zip) 

#### 1.2.11 Oxygen Refit

<img src="./preview/toolbar/Oxygen%20Refit.jpg" alt="Oxygen Refit" style="zoom:80%;" /> 

[Download This Icon Group](./Toolbar/Oxygen%20Refit.zip) 

#### 1.2.12 7-Zip Original

<img src="./preview/toolbar/7-Zip%20Original%20Toolbar%20Theme.jpg" alt="7-Zip Original" style="zoom:80%;" /> 

[Download This Icon Group](./Toolbar/7-Zip%20Original%20Toolbar%20Theme.zip) 

## 2. 注册表

<img alt='register' src="./preview/option.png" width="420"  > 

```register
Windows Registry Editor Version 5.00

[HKEY_CLASSES_ROOT\.lzma]
@="7-Zip.lzma"

[HKEY_CLASSES_ROOT\7-Zip.lzma]
@="7z Archive"

[HKEY_CLASSES_ROOT\7-Zip.lzma\DefaultIcon]
@="C:\\Program Files\\7-Zip\\7z.dll,16"

[HKEY_CLASSES_ROOT\7-Zip.lzma\shell]
@=""

[HKEY_CLASSES_ROOT\7-Zip.lzma\shell\open]
@=""

[HKEY_CLASSES_ROOT\7-Zip.lzma\shell\open\command]
@=""
```





## 3. 特别声明

1、本软件相关资源收集自互联网，版权归其开发厂商及作者所有。

2、本软件仅限于个人学习交流，请勿用于任何形式商业用途。

3、您必须自行承担使用过程所有可能引起的后果及损失。

4、使用过程中若有意见或建议，请及时反馈和指正。