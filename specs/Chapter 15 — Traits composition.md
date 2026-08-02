Набор трейтов можно скомбинировать в один псевдотип:

```
compose MyTraitsGroup {
    Greeter
    Logger
    Printable
}
```

И использовать как алиас в объявлении классов:

```
class
uses MyTraitsGroup


```
