/* Russian presentation only. OSM keys and values in the datasets stay unchanged. */
(function(root){
'use strict';
const labels={name:'Название', 'name:ru':'Название по-русски', official_name:'Официальное название', old_name:'Прежнее название', loc_name:'Местное название',
 highway:'Класс дороги', ref:'Номер дороги', old_ref:'Прежний номер дороги', int_ref:'Международный номер', surface:'Покрытие',
 access:'Общий доступ', vehicle:'Доступ транспортных средств', motor_vehicle:'Доступ моторного транспорта', motorcar:'Доступ легковых автомобилей',
 hgv:'Доступ тяжёлых грузовиков', goods:'Доступ лёгких грузовиков', hgv_articulated:'Доступ автопоездов',
 maxweight:'Предел фактической полной массы', maxweightrating:'Предел разрешённой максимальной массы', maxaxleload:'Предел нагрузки на ось',
 maxheight:'Предельная высота', maxwidth:'Предельная ширина', maxlength:'Предельная длина', width:'Ширина дороги', height:'Высота',
 maxspeed:'Ограничение скорости', oneway:'Направление движения', lanes:'Количество полос', lit:'Освещение',
 bridge:'Мост', tunnel:'Тоннель', covered:'Проезд под навесом', toll:'Платный проезд', locked:'Закрыто на замок',
 barrier:'Препятствие', service:'Назначение проезда', smoothness:'Ровность покрытия', tracktype:'Тип покрытия просёлка',
 junction:'Тип пересечения', incline:'Уклон', sidewalk:'Тротуар', shoulder:'Обочина',
 living_street:'Жилая зона', construction:'Что строится', proposed:'Что планируется',
 destination:'Направление по указателю', 'destination:ref':'Номер дороги по указателю',
 foot:'Доступ пешеходов', bicycle:'Доступ велосипедов', motorcycle:'Доступ мотоциклов',
 opening_hours:'Время доступа', operator:'Оператор', fee:'Плата за пользование',
 entrance:'Вход или въезд', traffic_sign:'Дорожный знак', 'maxheight:physical':'Фактический просвет по высоте',
 'maxwidth:physical':'Фактический просвет по ширине', hazmat:'Доступ с опасным грузом', overtaking:'Обгон'};
const access={yes:'Разрешён по данным карты',no:'Запрещён по данным карты',destination:'Только к месту назначения, без сквозного проезда',
 delivery:'Только для доставки',private:'Частный доступ',permissive:'По разрешению владельца, которое может быть отозвано',
 customers:'Только для клиентов',permit:'По пропуску или разрешению',designated:'Предусмотрен для этого вида транспорта',
 agricultural:'Только сельскохозяйственный транспорт',forestry:'Только лесохозяйственный транспорт',unknown:'Неизвестно',discouraged:'Нежелателен по данным карты'};
const enums={
 highway:{motorway:'Автомагистраль',trunk:'Крупная транзитная дорога',primary:'Основная дорога',secondary:'Дорога среднего значения',
 tertiary:'Важная местная дорога',unclassified:'Местная соединительная дорога',residential:'Жилая улица',living_street:'Проезд в жилой зоне',
 service:'Подъездной или служебный проезд',track:'Полевая или лесная дорога',construction:'Строящаяся дорога',proposed:'Планируемая дорога',
 motorway_link:'Съезд или примыкание к автомагистрали',trunk_link:'Съезд или примыкание к транзитной дороге',primary_link:'Съезд или примыкание к основной дороге',
 secondary_link:'Съезд или примыкание к дороге среднего значения',tertiary_link:'Съезд или примыкание к местной дороге'},
 surface:{asphalt:'Асфальт',unpaved:'Без твёрдого покрытия',ground:'Грунт',dirt:'Грунт',earth:'Земляное покрытие',compacted:'Уплотнённый щебёночно-гравийный материал',
 paved:'Твёрдое покрытие, тип не уточнён',gravel:'Гравий',fine_gravel:'Мелкий гравий',paving_stones:'Тротуарная плитка',concrete:'Бетон',
 'concrete:plates':'Бетонные плиты','concrete:lanes':'Бетонные полосы под колёса',grass:'Трава',sand:'Песок',mud:'Грязь',clay:'Глина',
 cobblestone:'Булыжник',sett:'Брусчатка',wood:'Деревянное покрытие',metal:'Металлическое покрытие'},
 oneway:{yes:'Одностороннее',no:'Двустороннее','-1':'Одностороннее, против направления линии на карте',reversible:'Реверсивное',alternating:'Попеременно в двух направлениях'},
 service:{driveway:'Подъезд к объекту',parking_aisle:'Проезд по парковке',alley:'Узкий переулок',drive_through:'Проезд для обслуживания из автомобиля',emergency_access:'Проезд экстренных служб'},
 barrier:{gate:'Ворота',lift_gate:'Подъёмный шлагбаум',swing_gate:'Поворотный шлагбаум',block:'Блок, перекрывающий проезд',entrance:'Проход или проезд в ограждении',
 wicket_gate:'Калитка',bollard:'Ограничительный столбик',kerb:'Бордюр',chain:'Цепь',yes:'Препятствие, тип не уточнён',log:'Бревно',debris:'Завал',
 planter:'Цветочница, перекрывающая проезд',cycle_barrier:'Ограждение для ограничения проезда велосипедов',fence:'Забор',toll_booth:'Пункт оплаты',
 hampshire_gate:'Проволочные ворота',kissing_gate:'Пешеходная калитка с ограничителем',tree:'Дерево',sally_port:'Шлюзовой проезд',ditch:'Канава',
 stile:'Пешеходный перелаз',guard_rail:'Дорожное ограждение',turnstile:'Турникет',parking_lock:'Парковочный блокиратор'},
 smoothness:{excellent:'Отличная',very_good:'Очень хорошая',good:'Хорошая',intermediate:'Средняя',bad:'Плохая',very_bad:'Очень плохая',horrible:'Крайне плохая',very_horrible:'Очень тяжёлые условия',impassable:'Непроезжая по данным карты'},
 tracktype:{grade1:'Твёрдое покрытие',grade2:'Преимущественно твёрдый уплотнённый материал',grade3:'Смешанное твёрдое и мягкое покрытие',grade4:'Преимущественно мягкое покрытие',grade5:'Мягкое покрытие'},
 junction:{roundabout:'Круговое движение',circular:'Кольцевое пересечение'},
 sidewalk:{both:'С обеих сторон',left:'Слева по направлению линии',right:'Справа по направлению линии',yes:'Есть',no:'Нет',separate:'Нанесён отдельной линией'},
 shoulder:{both:'С обеих сторон',left:'Слева по направлению линии',right:'Справа по направлению линии',yes:'Есть',no:'Нет'},
 tunnel:{yes:'Есть',no:'Нет',building_passage:'Проезд через здание',culvert:'Водопропускная труба'},
 bridge:{yes:'Есть',no:'Нет',viaduct:'Виадук',movable:'Разводной мост'},
 entrance:{yes:'Есть',main:'Основной',service:'Служебный',emergency:'Аварийный',exit:'Выход',no:'Нет'},
 maxspeed:{'RU:rural':'Общее правило для дорог вне населённых пунктов; зависит от транспорта',
 'RU:urban':'Общее правило для населённых пунктов; зависит от транспорта','RU:living_street':'Общее правило для жилой зоны',
 'RU:motorway':'Общее правило для автомагистралей; зависит от транспорта',none:'Числовой предел не указан',walk:'Скорость пешехода'},
 incline:{up:'Подъём по направлению линии',down:'Спуск по направлению линии'},
 overtaking:{yes:'Разрешён по данным карты',no:'Запрещён по данным карты'}};
const accessKeys=new Set(['access','vehicle','motor_vehicle','motorcar','hgv','goods','hgv_articulated','foot','bicycle','motorcycle','hazmat']);
const boolKeys=new Set(['lit','covered','toll','locked','living_street','fee','bridge','tunnel']);
const textKeys=new Set(['name','name:ru','official_name','old_name','loc_name','ref','old_ref','int_ref','destination','destination:ref','operator']);
const unitKeys={maxweight:'т',maxweightrating:'т',maxaxleload:'т',maxheight:'м',maxwidth:'м',maxlength:'м',width:'м',height:'м',maxspeed:'км/ч'};
const unknown='Необычное значение — см. исходные данные';
function keyInfo(key){
 if(labels[key])return {label:labels[key],base:key,conditional:false};
 const match=key.match(/^(.*):(conditional|forward|backward|hgv|hgv_articulated|physical)$/);
 if(!match)return null;
 const p=keyInfo(match[1]);if(!p)return null;
 const suffix={conditional:'при определённых условиях',forward:'по направлению линии',backward:'против направления линии',hgv:'для тяжёлых грузовиков',hgv_articulated:'для автопоездов',physical:'фактический габарит'}[match[2]];
 return {label:p.label+' — '+suffix,base:p.base,conditional:p.conditional||match[2]==='conditional'};
}
function value(key,value){
 const info=keyInfo(key);const v=String(value);if(!info)return null;
 if(info.conditional)return 'Действует при определённых условиях; требуется разбор исходного правила';
 let base=info.base;
 if(base==='maxheight:physical')base='maxheight';if(base==='maxwidth:physical')base='maxwidth';
 if(textKeys.has(base))return v.replace(/;/g,'; ');
 if(accessKeys.has(base))return access[v]||unknown;
 if(enums[base]){
   if(enums[base][v])return enums[base][v];
   if(v.includes(';'))return v.split(';').map(x=>enums[base][x.trim()]||unknown).join('; ');
 }
 if(base==='construction'||base==='proposed')return enums.highway[v]||unknown;
 if(boolKeys.has(base)&&['yes','no'].includes(v))return v==='yes'?'Да':'Нет';
 if(unitKeys[base]){
   if(/^\d+(\.\d+)?$/.test(v))return v.replace('.',',')+' '+unitKeys[base];
   if(v==='unsigned')return 'Числовой предел не указан на знаке';
   if(v==='none')return 'Отдельный предел не указан; общие правила сохраняются';
   if(v==='default')return 'Действует общее правило';
   return unknown;
 }
 if(base==='lanes'&&/^\d+$/.test(v))return v;
 if(base==='incline'&&/^-?\d+(\.\d+)?%?$/.test(v))return v.replace('.',',');
 if(base==='opening_hours')return 'Расписание указано; см. исходные данные';
 if(base==='traffic_sign')return 'Знак указан кодом; см. исходные данные';
 return unknown;
}
function rows(tags){return Object.entries(tags).flatMap(([k,v])=>{const info=keyInfo(k);return info?[[info.label,value(k,v)]]:[];});}
const api={label:key=>keyInfo(key)?.label||null,value,rows,accessValue:v=>access[v]||'Требует проверки по исходным данным'};
root.roadLabelsRu=api;
if(typeof module!=='undefined'&&module.exports)module.exports=api;
}(typeof window!=='undefined'?window:globalThis));
